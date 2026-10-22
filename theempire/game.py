"""Game rules: units, cities, movement, combat, production, WMD and victory.

The rules follow the classic grid conquest games (one unit per cell outside cities, cities build one
item at a time, transports and carriers carry cargo, air units burn fuel)
with Theatre Europe's escalation ladder on top: chemical weapons, nuclear
strikes, retaliation and a Doomsday Clock that ends the game for everybody
when it reaches midnight.
"""

from __future__ import annotations

import heapq
import json
import random
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from theempire import cards, events, i18n, missions, regions
from theempire.i18n import N, Msg
from theempire.scenarios import SCENARIOS, Scenario
from theempire.units import (ASAT, CHEMICAL, MODERN, SATELLITE, UNIT_TYPES, WARHEAD,
                             UnitType, production_cost)
from theempire.world import World, load_world

DIFFICULTY = {N("facile"): 0.75, N("normale"): 1.0, N("difficile"): 1.3}
FALLOUT_TURNS = 12
IRRADIATED_TURNS = 10
UNREST_TURNS = 5
CHEM_RANGE = 4
MILITIA_ATTACK, MILITIA_DEFENSE = 1, 1
CITY_DEFENSE_BONUS = 1.5
FORTIFY_BONUS = 1.25
SUPPORT_BONUS = 0.15                # per friendly land unit next to the target
SUPPORT_MAX = 4
SUPPLY_FACTOR = 2.0                 # unit cap = factor x base production + 20
CLOCK_RECOVERY_TURNS = 6
SATELLITE_SWATH = 12                # a spy satellite watches 25 columns of the world...
SATELLITE_STEP = 30                 # ...and moves this many columns every round
ASAT_CHANCE = 0.75                  # an anti-satellite weapon hits
TRUCE_TURNS = 15

# Production directives: one order that sets what every city builds.
DIRECTIVES = {
    "": N("manuale (decidi città per città)"),
    "auto": N("bilanciata (decide l'IA)"),
    "land": N("offensiva terrestre (corazzati e fanteria)"),
    "air": N("potenza aerea (caccia e bombardieri)"),
    "sea": N("dominio dei mari (flotta nei porti)"),
    "amphibious": N("sbarchi (trasporti nei porti, truppe altrove)"),
    "defense": N("difesa (fanteria ovunque)"),
    "nuclear": N("deterrenza (testate nelle grandi città)"),
}


@dataclass
class Unit:
    id: int
    kind: str
    owner: int
    cell: int
    hp: int
    moves: int
    fuel: int = 0
    carrier: int | None = None          # id of the transport/carrier holding it
    cargo: list[int] = field(default_factory=list)
    order: str | None = None            # sentry | fortify | goto | auto
    target: int | None = None           # goto destination

    @property
    def type(self) -> UnitType:
        return UNIT_TYPES[self.kind]


@dataclass
class City:
    id: int
    name: str
    iso: str
    cell: int
    size: int
    capital: bool
    owner: int | None
    production: str = "I"
    progress: float = 0.0
    militia: int = 1
    irradiated: int = 0
    unrest: int = 0
    founder: int | None = None          # owner at the start of the game
    manual: bool = False                # production picked by hand: directives leave it

    def militia_max(self) -> int:
        if self.owner is None:
            return self.size + 1 + (1 if self.capital else 0)
        return self.size + (1 if self.capital else 0)


@dataclass
class Faction:
    idx: int
    key: str
    name: str
    color: str
    human: bool
    doctrine: str
    warheads: int
    chemicals: int
    abm: float
    nuclear: bool
    industry: float
    alive: bool = True
    nuked_by: list[int] = field(default_factory=list)   # pending retaliation
    used_wmd: int = 0
    kills: int = 0
    losses: int = 0
    start_cities: int = 0
    auto_production: bool = False       # let the AI pick what human cities build
    directive: str = ""                 # production directive ("" = by hand), see DIRECTIVES
    cards: list[str] = field(default_factory=list)     # the hand (see cards.py)
    effects: dict = field(default_factory=dict)        # card effects: name -> last turn
    conquests: int = 0                  # cities taken this turn (earns a card)
    mission: dict = field(default_factory=dict)        # the secret objective (see missions.py)
    satellites: list[int] = field(default_factory=list)  # orbits: the column each one flies over
    asats: int = 0                      # anti-satellite weapons in stock


@dataclass
class Event:
    turn: int
    text: str
    audience: list[int] | None = None   # None = everybody
    level: str = "info"                 # info | combat | alert | wmd | chat
    sound: str = ""                     # effect the interface may play
    actor: int | None = None            # faction that caused it
    seq: int = 0                        # increasing id, to spot new events
    kind: str = ""                      # unit type behind it, for its own sound
    msg: list | None = None             # [template, params]: translated by the reader (i18n)

    def shown(self, lang: str | None = None) -> str:
        """The text in the reader's language."""
        return i18n.render(self.msg, lang) if self.msg else i18n.word(self.text, lang)


class Game:
    def __init__(self, scenario: str = "ww3", humans: tuple[str, ...] = (),
                 difficulty: str = "normale", seed: int | None = None,
                 world: World | None = None, _empty: bool = False,
                 objectives: bool | None = None, world_events: bool | None = None,
                 realtime: int = 0, hexgrid: bool | None = None):
        if hexgrid is None:
            hexgrid = world.hexgrid if world is not None else False
        if world is None or world.hexgrid != hexgrid:
            world = load_world(hexgrid)
        self.world = world
        self.scenario: Scenario = SCENARIOS[scenario]
        self.difficulty = difficulty
        # rules that can be switched off (default: as the scenario says)
        self.options = {
            "missions": self.scenario.missions if objectives is None else objectives,
            "world_events": self.scenario.world_events if world_events is None else world_events,
            # real time: seconds between two pulses (0 = turns, one faction at a time)
            "realtime": max(0, int(realtime)),
            # hexagons instead of squares: 6 neighbours instead of 8
            "hex": bool(hexgrid),
        }
        self.rng = random.Random(seed)
        self.turn = 1
        self.current = 0
        self.doomsday = self.scenario.doomsday
        self.quiet_turns = 0
        self.fallout: dict[int, int] = {}
        self.events: list[Event] = []
        self.event_seq = 0
        self.over: tuple[int | None, str] | None = None
        self.truces: dict[str, int] = {}     # "a-b" -> last turn of the truce
        self.proposals: list[list[int]] = []  # [from, to] truce offers pending
        self.offered: dict[str, int] = {}    # "from>to" -> turn of the last offer
        self.prepared: list[int] | None = None  # [turn, faction] of the last prepared human turn
        self.units: dict[int, Unit] = {}
        self.at: dict[int, list[int]] = {}
        self.next_id = 1
        self.deck: list[str] = []      # the card deck (top = end) and the discards
        self.discard: list[str] = []
        self.reel: list[dict] = []     # every action, for the war bulletin (not saved)
        self.reel_seq = 0
        self.reel_mark: dict[int, int] = {}  # faction -> last action it has been shown
        self._vis: dict[int, set[int]] = {}
        self._det: dict[int, set[int]] = {}
        self.region_holders: dict[str, int | None] = {}  # see regions.py
        self.world_effects: dict[str, int] = {}          # world event -> last turn (events.py)
        self.next_event = 0                              # round of the next world event
        self.theatre = self._theatre_mask()              # None: the whole world is in play
        if _empty:
            return
        self.factions: list[Faction] = []
        self.cities: list[City] = []
        self.city_at: dict[int, int] = {}
        for k, fd in enumerate(self.scenario.factions):
            self.factions.append(Faction(
                k, fd.key, fd.name, fd.color, fd.key in humans, fd.doctrine,
                fd.warheads, fd.chemicals, fd.abm, fd.nuclear, fd.industry))
        owner_of_iso = {iso: k for k, fd in enumerate(self.scenario.factions) for iso in fd.countries}
        for site in self.world.sites:
            if not self.in_theatre(site.cell) or site.iso in self.scenario.outside:
                continue
            owner = owner_of_iso.get(site.iso)
            for name, key in self.scenario.city_owners:
                if name == site.name:
                    owner = next(k for k, fd in enumerate(self.scenario.factions) if fd.key == key)
            for k, fd in enumerate(self.scenario.factions):
                if fd.capital_city and fd.capital_city == site.name:
                    owner = k
            city = City(len(self.cities), site.name, site.iso, site.cell, site.size,
                        site.capital, owner, founder=owner)
            city.militia = city.militia_max()
            self.cities.append(city)
            self.city_at[site.cell] = city.id
        for f in self.factions:
            f.start_cities = len(self.cities_of(f.idx))
        self._place_start_forces()
        for f in self.factions:
            for c in self.cities_of(f.idx):
                c.production = self._default_production(c)
        self.deck = cards.new_deck(self.rng)
        regions.update(self)
        if self.options["missions"]:
            missions.assign(self)
        if self.options["world_events"]:
            events.schedule(self)
        self.log(Msg("{scenario}: la guerra è cominciata. Orologio dell'Apocalisse "
                     "a {minutes} minuti dalla mezzanotte.",
                     scenario=self.scenario.name, minutes=self.doomsday), level="alert")
        self.begin_turn()

    # ------------------------------------------------------------------ setup
    def _place_start_forces(self) -> None:
        for f, fd in zip(self.factions, self.scenario.factions):
            cities = sorted(self.cities_of(f.idx), key=lambda c: (-c.size, -c.capital, c.id))
            if not cities:
                continue
            if not self.scenario.start_forces:
                for kind in "IA":
                    self.create_unit(kind, f.idx, cities[0].cell)
                continue
            for c in cities:
                kinds = {1: "I", 2: "IA", 3: "IIAF"}[c.size]
                if c.capital:
                    kinds += "AF"
                if self.is_port(c.cell) and c.size >= 2:
                    kinds += "D"
                    if c.capital:
                        kinds += "TR"
                for k in kinds:
                    u = self.create_unit(k, f.idx, c.cell)
                    u.order = "fortify" if k == "I" else "sentry"
            ports = [c for c in cities if self.is_port(c.cell)] or cities
            big = cities
            for kind, n in fd.extras.items():
                pool = ports if UNIT_TYPES[kind].domain == "sea" else big
                for j in range(n):
                    host = pool[j % len(pool)]
                    u = self.create_unit(kind, f.idx, host.cell)
                    u.order = "sentry"
                    if kind == "C":
                        for _ in range(2):
                            fighter = self.create_unit("F", f.idx, host.cell)
                            self._embark(fighter, u)

    def _default_production(self, c: City) -> str:
        return "A" if c.size >= 2 else "I"

    # ---------------------------------------------------------------- queries
    def record(self, op: str, cell: int, actor: int | None, **extra) -> dict:
        """Note one action for the war bulletin, whoever made it (AI or
        another player): each faction is later shown what happened since
        its own last turn (see take_reel)."""
        self.reel_seq += 1
        self.reel.append({"op": op, "cell": cell, "actor": actor, "seq": self.reel_seq,
                          "turn": self.turn, **extra})
        if len(self.reel) > 20000:
            del self.reel[:5000]
        return self.reel[-1]

    def take_reel(self, f: int) -> list[dict]:
        """The actions of others since faction ``f`` last saw the bulletin."""
        mark = self.reel_mark.get(f, 0)
        self.reel_mark[f] = self.reel_seq
        return [a for a in self.reel if a["seq"] > mark and a["actor"] != f]

    def log(self, text: "str | i18n.Msg", audience: list[int] | None = None, level: str = "info",
            sound: str = "", actor: int | None = None, kind: str = "") -> None:
        """Write in the war log. A Msg is translated by each reader."""
        self.event_seq += 1
        msg = text.to_json() if isinstance(text, i18n.Msg) else None
        self.events.append(Event(self.turn, str(text), audience, level, sound, actor,
                                 self.event_seq, kind, msg))
        if len(self.events) > 400:
            del self.events[:100]

    def cities_of(self, owner: int | None) -> list[City]:
        return [c for c in self.cities if c.owner == owner]

    def units_of(self, owner: int) -> list[Unit]:
        return [u for u in self.units.values() if u.owner == owner]

    def units_at(self, cell: int) -> list[Unit]:
        return [self.units[i] for i in self.at.get(cell, ())]

    def city(self, cell: int) -> City | None:
        cid = self.city_at.get(cell)
        return self.cities[cid] if cid is not None else None

    def is_port(self, cell: int) -> bool:
        return any(not self.world.land[n] for n in self.world.neighbors[cell])

    def faction_name(self, owner: int | None) -> str:
        return N("Neutrali") if owner is None else self.factions[owner].name

    def visible(self, f: int) -> set[int]:
        vis = self._vis.get(f)
        if vis is None:
            vis = set()
            w = self.world
            for c in self.cities:
                if c.owner == f:
                    vis.update(w.ring(c.cell, 2))
            for u in self.units.values():
                if u.owner == f and u.carrier is None:
                    vis.update(w.ring(u.cell, u.type.vision))
            for x in self.factions[f].satellites:   # from orbit, a band of the whole world
                for col in self.satellite_band(x):
                    col %= w.width
                    vis.update(range(col, w.size, w.width))
            spied = cards.spied(self, f)
            if spied is not None:   # the spies report every enemy position
                vis.update(u.cell for u in self.units.values() if u.owner == spied)
            self._vis[f] = vis
        return vis

    def sees(self, f: int, u: Unit) -> bool:
        if u.owner == f:
            return True
        if u.cell not in self.visible(f):
            return False
        if u.type.stealth and u.carrier is None:
            return u.cell in self._detection(f)
        return True

    def _detection(self, f: int) -> set[int]:
        """Cells where faction f can spot submarines."""
        det = self._det.get(f)
        if det is None:
            det = set()
            w = self.world
            for c in self.cities:
                if c.owner == f:
                    det.update(w.ring(c.cell, 1))
            for o in self.units.values():
                if o.owner == f and o.carrier is None:
                    det.update(w.ring(o.cell, 2 if o.kind == "D" else 1))
            self._det[f] = det
        return det

    def _dirty(self) -> None:
        self._vis.clear()
        self._det.clear()

    # ------------------------------------------------------------ unit basics
    def create_unit(self, kind: str, owner: int, cell: int) -> Unit:
        t = UNIT_TYPES[kind]
        u = Unit(self.next_id, kind, owner, cell, t.hp, t.move, t.fuel)
        self.next_id += 1
        self.units[u.id] = u
        self.at.setdefault(cell, []).append(u.id)
        self._dirty()
        return u

    def _detach(self, u: Unit) -> None:
        if u.carrier is not None:
            carrier = self.units.get(u.carrier)
            if carrier and u.id in carrier.cargo:
                carrier.cargo.remove(u.id)
            u.carrier = None
        else:
            ids = self.at.get(u.cell)
            if ids and u.id in ids:
                ids.remove(u.id)
                if not ids:
                    del self.at[u.cell]

    def _place(self, u: Unit, cell: int) -> None:
        u.cell = cell
        self.at.setdefault(cell, []).append(u.id)
        for cid in u.cargo:
            self.units[cid].cell = cell

    def _embark(self, u: Unit, carrier: Unit) -> None:
        self._detach(u)
        u.carrier = carrier.id
        u.cell = carrier.cell
        carrier.cargo.append(u.id)
        u.order = "sentry"
        if u.type.domain == "air":
            u.fuel = u.type.fuel

    def kill(self, u: Unit, reason: str = "") -> None:
        for cid in list(u.cargo):
            if cid in self.units:
                self.kill(self.units[cid])
        self._detach(u)
        self.units.pop(u.id, None)
        self.factions[u.owner].losses += 1
        self._dirty()

    def has_room(self, carrier: Unit) -> bool:
        return len(carrier.cargo) < carrier.type.capacity

    # ---------------------------------------------------------------- movement
    def _theatre_mask(self) -> bytearray | None:
        bounds = self.scenario.bounds
        if bounds is None:
            return None
        w = self.world
        sea = self.scenario.sea_bounds or bounds

        def inside(i: int, box) -> bool:
            west, east, south, north = box
            lon, lat = w.lonlat(i)
            return west <= lon <= east and south <= lat <= north
        return bytearray(1 if inside(i, bounds if w.land[i] else sea) else 0 for i in range(w.size))

    def in_theatre(self, cell: int) -> bool:
        """Is this cell part of the war (always, unless the scenario has a theatre)?"""
        return self.theatre is None or bool(self.theatre[cell])

    def terrain_ok(self, kind: str, cell: int, owner: int) -> bool:
        """Can a unit of this kind stand on this cell (ignoring other units)?"""
        if self.theatre is not None and not self.theatre[cell]:
            return False
        domain = UNIT_TYPES[kind].domain
        if domain == "air":
            return True
        if domain == "land":
            return bool(self.world.land[cell])
        if not self.world.land[cell]:
            return True
        c = self.city(cell)
        return c is not None and c.owner == owner and self.is_port(cell)

    def classify(self, u: Unit, cell: int) -> str | None:
        """What happens if ``u`` steps onto the adjacent ``cell``.

        One of: move, board, attack, None (impossible)."""
        if cell not in self.world.neighbors[u.cell]:
            return None
        t = u.type
        city = self.city(cell)
        others = self.units_at(cell)
        if city is not None and city.owner != u.owner and not self.hostile(u.owner, city.owner):
            return None  # a city of a truce partner
        hostile_city = city is not None and city.owner != u.owner
        enemies = [o for o in others if self.hostile(u.owner, o.owner)]
        if enemies or hostile_city:
            return "attack" if self.can_attack(u, cell) else None
        if any(o.owner != u.owner for o in others):
            return None  # units of a truce partner
        if city is not None:  # own city
            if t.domain == "sea" and not self.is_port(cell):
                return None
            return "move"
        if self.carrier_at(u, cell) is not None:
            return "board"
        # Aircraft fly over your units: outside cities a cell holds at most
        # one aircraft and one unit on the ground (or at sea) below it.
        if any((o.type.domain == "air") == (t.domain == "air") for o in others):
            return None
        return "move" if self.terrain_ok(u.kind, cell, u.owner) else None

    def carrier_at(self, u: Unit, cell: int) -> Unit | None:
        """An own transport or carrier at ``cell`` with room for ``u``."""
        if u.type.domain == "sea":
            return None
        for o in self.units_at(cell):
            if o.owner == u.owner and o.type.carries == u.type.domain and self.has_room(o):
                return o
        return None

    def can_attack(self, u: Unit, cell: int) -> bool:
        t = u.type
        if t.attack <= 0:
            return False
        city = self.city(cell)
        targets = [o for o in self.units_at(cell) if self.hostile(u.owner, o.owner)]
        if not targets and city is None:
            return False
        if t.key == "S":
            return bool(targets) and city is None and not self.world.land[cell]
        if t.domain == "land":
            if u.carrier is None and not self.world.land[cell]:
                return False
            return bool(self.world.land[cell])
        if t.domain == "sea":
            # Ships fight ships, or bombard the shore next to them.
            return True
        return True  # air

    def move(self, u: Unit, cell: int) -> str:
        """Try one step. Returns a short outcome code for the UI and AI."""
        if self.over or u.moves <= 0:
            return "nomoves"
        action = self.classify(u, cell)
        if action is None:
            hidden = [o for o in self.units_at(cell)
                      if self.hostile(u.owner, o.owner) and not self.sees(u.owner, o)]
            if hidden:
                self.log(Msg("{unit}: contatto con un'unità nascosta!", unit=u.type.name),
                         [u.owner], "combat", "alert", u.owner)
                u.moves = 0
                self._dirty()
                return "blocked"
            return "illegal"
        if action == "attack":
            return self.attack(u, cell)
        self._spend(u)
        if action == "board":
            self._embark(u, self.carrier_at(u, cell))
            u.moves = 0
        else:
            disembark = u.carrier is not None
            self._detach(u)
            self._place(u, cell)
            if disembark:
                u.moves = 0
                u.order = None
        if u.type.domain == "air":
            self._air_after_move(u)
        self._dirty()
        self._wake_sentries(u)
        if u.id in self.units:
            self.record("move", cell, u.owner, unit=u.id, glyph=u.kind, owner=u.owner)
        return "moved" if u.id in self.units else "crashed"

    def _spend(self, u: Unit) -> None:
        u.moves -= 1
        if u.type.domain == "air":
            u.fuel -= 1

    def _air_after_move(self, u: Unit) -> None:
        if u.id not in self.units:
            return
        if u.carrier is not None:
            u.fuel = u.type.fuel
            return
        c = self.city(u.cell)
        if c is not None and c.owner == u.owner:
            u.fuel = u.type.fuel
            return
        if u.fuel <= 0:
            # one sentence per aircraft: the article and the case differ by language
            if u.kind == "B":
                msg = Msg("Un bombardiere è rimasto senza carburante ed è precipitato.")
            else:
                msg = Msg("Un caccia è rimasto senza carburante ed è precipitato.")
            self.log(msg, [u.owner], "combat", "crash", u.owner)
            self.kill(u)

    def _wake_sentries(self, mover: Unit) -> None:
        """Enemy units on sentry duty wake up when ``mover`` comes close."""
        for o in self.units.values():
            if self.hostile(o.owner, mover.owner) and o.order == "sentry" and o.carrier is None \
                    and self.world.dist(o.cell, mover.cell) <= 2 and self.sees(o.owner, mover):
                o.order = None

    def unload(self, carrier: Unit) -> int:
        """Put the cargo of a ship sitting in a city onto the city."""
        if self.city(carrier.cell) is None:
            return 0
        n = 0
        for cid in list(carrier.cargo):
            cu = self.units[cid]
            self._detach(cu)
            self._place(cu, carrier.cell)
            cu.order = None
            n += 1
        return n

    def load(self, carrier: Unit) -> int:
        """Load the units sharing a city with the carrier (fortified ones stay)."""
        if self.city(carrier.cell) is None or not carrier.type.carries:
            return 0
        n = 0
        for o in self.units_at(carrier.cell):
            if o is carrier or o.owner != carrier.owner or o.type.domain != carrier.type.carries \
                    or o.order == "fortify":
                continue
            if not self.has_room(carrier):
                break
            self._embark(o, carrier)
            n += 1
        return n

    # ------------------------------------------------------------- pathfinding
    def path(self, u: Unit, dest: int, avoid_units: bool = False, limit: int = 4000) -> list[int] | None:
        """A* over terrain; returns the cells after u.cell up to dest."""
        if dest == u.cell:
            return []
        if not self.in_theatre(dest):
            return None
        w = self.world
        start = u.cell
        kind, owner = u.kind, u.owner
        domain = u.type.domain

        def passable(c: int) -> bool:
            if c == dest:
                return True
            if domain == "land" and u.carrier is not None and c == start:
                return True
            if not self.terrain_ok(kind, c, owner):
                return False
            city = self.city(c)
            if city is not None and city.owner != owner:
                return False
            if avoid_units and city is None and any(
                    o.owner != owner or (o.type.domain == "air") == (domain == "air")
                    for o in self.units_at(c)):
                return False
            return True

        if not passable(dest) and domain != "air":
            return None
        if domain == "land" and not w.land[dest]:
            return None
        # Among the many equally short routes of the grid, prefer the
        # one closest to the straight line from start to dest (no zig-zags).
        dx0, dy0 = w.offset(dest, start)

        def off_line(c: int) -> int:
            dx, dy = w.offset(dest, c)
            return abs(dx * dy0 - dy * dx0)

        frontier = [(w.dist(start, dest), 0, 0, start)]
        came = {start: None}
        cost = {start: 0}
        done: set[int] = set()
        while frontier:
            _, _, g, c = heapq.heappop(frontier)
            if c == dest:
                break
            if c in done:
                continue                # an older, longer entry of a cell already settled
            done.add(c)
            if len(done) > limit:
                return None
            for n in w.neighbors[c]:
                if n in done or (n in cost and cost[n] <= g + 1) or not passable(n):
                    continue
                cost[n] = g + 1         # a shorter way to n: keep this one
                came[n] = c
                heapq.heappush(frontier, (g + 1 + w.dist(n, dest), off_line(n), g + 1, n))
        if dest not in came:
            return None
        out = []
        c = dest
        while c != start:
            out.append(c)
            c = came[c]
        out.reverse()
        return out

    def follow_goto(self, u: Unit) -> None:
        """Advance a unit along its goto order as far as its moves allow."""
        guard = 0
        while u.id in self.units and u.order == "goto" and u.moves > 0 and guard < 20:
            guard += 1
            if u.cell == u.target:
                u.order, u.target = None, None
                return
            route = self.path(u, u.target)
            if not route:
                u.order, u.target = None, None
                self.log(Msg("{unit}: destinazione irraggiungibile.", unit=u.type.name), [u.owner])
                return
            step = route[0]
            action = self.classify(u, step)
            if action == "attack" and step != u.target:
                u.order, u.target = None, None  # enemy in the way: ask the player
                return
            if action is None:
                detour = self.path(u, u.target, avoid_units=True, limit=600)
                if detour and self.classify(u, detour[0]) in ("move", "board"):
                    step = detour[0]
                else:
                    return  # wait for the road to clear
            self.move(u, step)
            if u.id in self.units and u.carrier is not None and u.type.domain == "land":
                u.order, u.target = None, None

    # ----------------------------------------------------------------- combat
    def defender_at(self, attacker: Unit, cell: int) -> Unit | None:
        enemies = [o for o in self.units_at(cell) if self.hostile(attacker.owner, o.owner)]
        if not enemies:
            return None
        return max(enemies, key=lambda o: self.defense_value(attacker, o) * o.hp)

    def attack_value(self, a: Unit, cell: int, target: Unit | None) -> float:
        v = float(a.type.attack)
        if a.carrier is not None and a.type.domain == "land":
            v *= 0.5                                  # amphibious assault
        if a.type.domain == "land" and self.world.land[cell]:
            v *= 1 + SUPPORT_BONUS * self.support(a, cell)
        if target is not None:
            if a.kind == "D" and target.kind == "S":
                v *= 2
            if a.kind == "F" and target.type.domain == "air":
                v *= 1.5
            if a.kind == "B" and target.type.domain == "sea":
                v *= 0.75
            if a.type.domain == "sea" and target.type.domain == "land" and a.kind != "R":
                v *= 0.5
        return v

    def support(self, a: Unit, cell: int) -> int:
        """Friendly land units, besides the attacker, adjacent to the target."""
        n = 0
        for c in self.world.neighbors[cell]:
            if c == a.cell:
                continue
            for o in self.units_at(c):
                if o.owner == a.owner and o.type.domain == "land":
                    n += 1
                    break
        return min(n, SUPPORT_MAX)

    def defense_value(self, a: Unit, d: Unit) -> float:
        v = float(d.type.defense)
        c = self.city(d.cell)
        if c is not None:
            v *= CITY_DEFENSE_BONUS
        if d.order == "fortify" and d.type.domain == "land":
            v *= FORTIFY_BONUS
        if d.kind == "S" and a.kind == "D":
            v *= 0.5
        return v

    def odds(self, u: Unit, cell: int) -> float | None:
        """Chance that ``u`` wins its next fight at ``cell`` (for the UI and AI)."""
        if not self.can_attack(u, cell):
            return None
        d = self.defender_at(u, cell)
        av = self.attack_value(u, cell, d)
        if d is not None:
            return win_probability(av, u.hp, self.defense_value(u, d), d.hp)
        c = self.city(cell)
        if c is None:
            return None
        return win_probability(av, u.hp, MILITIA_DEFENSE * CITY_DEFENSE_BONUS, max(1, c.militia))

    def supply_limit(self, f: int) -> int:
        fac = self.factions[f]
        base = sum(c.size + (1 if c.capital else 0) for c in self.cities if c.owner == f)
        return int(SUPPLY_FACTOR * base * fac.industry) + 20

    def attack(self, u: Unit, cell: int) -> str:
        """Fight at ``cell``; the bulletin keeps who attacked from where,
        what defended and how it ended, to replay the battle."""
        city = self.city(cell)
        d = self.defender_at(u, cell)
        defender = d.owner if d is not None else (city.owner if city else None)
        act = self.record("attack", cell, u.owner, glyph=u.kind, owner=u.owner,
                          attacker=u.owner, defender=defender, frm=u.cell,
                          target=d.kind if d is not None else "")
        result = self._attack(u, cell, city, d)
        act["result"] = result
        return result

    def _attack(self, u: Unit, cell: int, city: City | None, d: Unit | None) -> str:
        av = self.attack_value(u, cell, d)
        self._spend(u)
        if u.type.domain == "land" and u.carrier is not None:
            u.moves = 0
        u.order = None
        if d is not None:
            dv = self.defense_value(u, d)
            ahp, dhp = fight(av, u.hp, dv, d.hp, self.rng)
            names = dict(faction=self.factions[u.owner].name, unit=u.type.name,
                         target=d.type.name, enemy=self.faction_name(d.owner))
            if ahp > 0:
                u.hp = ahp
                self.factions[u.owner].kills += 1
                if city:
                    msg = Msg("{faction}: {unit} distrugge {target} presso {city} ({enemy}).",
                              city=city.name, **names)
                else:
                    msg = Msg("{faction}: {unit} distrugge {target} ({enemy}).", **names)
                self.log(msg, [u.owner, d.owner], "combat", "battle", u.owner, u.kind)
                self.kill(d)
                result = "won"
            else:
                d.hp = dhp
                self.factions[d.owner].kills += 1
                if city:
                    msg = Msg("{faction}: {unit} distrutto attaccando {target} presso {city} ({enemy}).",
                              city=city.name, **names)
                else:
                    msg = Msg("{faction}: {unit} distrutto attaccando {target} ({enemy}).", **names)
                self.log(msg, [u.owner, d.owner], "combat", "battle", u.owner, u.kind)
                self.kill(u)
                return "lost"
        elif city is not None:
            defender_owner = city.owner
            ahp, mhp = fight(av, u.hp, MILITIA_DEFENSE * CITY_DEFENSE_BONUS, max(1, city.militia), self.rng)
            if ahp <= 0:
                city.militia = max(1, mhp)
                self.log(Msg("{unit} ({faction}) respinto dalla milizia di {city}.",
                             unit=u.type.name, faction=self.factions[u.owner].name, city=city.name),
                         [u.owner] + ([defender_owner] if defender_owner is not None else []), "combat",
                         "battle", u.owner, u.kind)
                self.kill(u)
                return "lost"
            u.hp = ahp
            city.militia = 0
            if u.type.capture:
                self.capture(city, u)
                return "captured"
            self.log(Msg("{city}: le difese sono a terra, serve la fanteria per occuparla.",
                         city=city.name), [u.owner])
            result = "won"
        else:
            return "illegal"
        if u.type.oneshot:              # a missile is spent in its strike
            self.kill(u)
        elif u.type.domain == "air":
            self._air_after_move(u)
        self._dirty()
        return result

    def capture(self, city: City, u: Unit) -> None:
        old = city.owner
        if u.owner == self.current or self.realtime:
            # may earn a card at the end of the turn
            self.factions[u.owner].conquests += cards.conquest_weight(city)
        city.owner = u.owner
        city.progress = 0.0
        city.unrest = UNREST_TURNS
        city.militia = 1
        city.production = self._default_production(city)
        self._detach(u)
        self._place(u, city.cell)
        u.moves = 0
        audience = None
        names = dict(faction=self.factions[u.owner].name, city=city.name, old=self.faction_name(old))
        if city.capital:
            msg = Msg("{faction} conquista CAPITALE {city} (prima: {old}).", **names)
        else:
            msg = Msg("{faction} conquista {city} (prima: {old}).", **names)
        self.log(msg, audience,
                 "alert" if city.capital or old is not None else "info", "capture", u.owner)
        self.record("capture", city.cell, u.owner, old=old, new=u.owner, name=city.name)
        if old is not None and not self.cities_of(old):
            self.record("fall", city.cell, u.owner, old=old)
            self.eliminate(old, by=u.owner)
        regions.update(self)
        self._dirty()

    def eliminate(self, f: int, by: int | None = None) -> None:
        """``f`` is out of the war, knocked out by ``by`` (default: the
        faction playing)."""
        fac = self.factions[f]
        if not fac.alive:
            return
        fac.alive = False
        missions.on_elimination(self, f, self.current if by is None else by)
        for u in self.units_of(f):
            if u.id in self.units:
                self.kill(u)
        self.log(Msg("{faction} ha perso l'ultima città ed è fuori dalla guerra.", faction=fac.name),
                 None, "alert", "fall", f)

    # -------------------------------------------------------------------- WMD
    def nuclear_strike(self, f: int, cell: int) -> str:
        fac = self.factions[f]
        if fac.warheads <= 0 or self.over:
            return "nowarheads"
        fac.warheads -= 1
        fac.used_wmd += 1
        self.quiet_turns = 0
        w = self.world
        city = self.city(cell)
        victim = city.owner if city else None
        if victim is None:
            owners = [o.owner for o in self.units_at(cell) if o.owner != f]
            victim = owners[0] if owners else None
        if victim is not None and victim != f and not self.hostile(f, victim):
            fac.warheads += 1
            fac.used_wmd -= 1
            return "truce"
        place = city.name if city else _coords(w, cell)
        abm = 0.0
        if victim is not None:
            abm = self.factions[victim].abm + (0.5 if cards.active(self, victim, "shield") else 0.0)
        if victim is not None and victim != f and self.rng.random() < abm:
            self.doomsday -= 1
            self.log(Msg("☢ {faction} lancia un missile nucleare su {place}: intercettato "
                         "dalla difesa antimissile di {victim}!",
                         faction=fac.name, place=place, victim=self.factions[victim].name),
                     None, "wmd", "intercept", f)
            self.factions[victim].nuked_by.append(f)
            self._check_clock()
            return "intercepted"
        killed = 0
        for c in w.ring(cell, 1):
            for o in self.units_at(c):
                if o.kind == "S" and c != cell and self.rng.random() < 0.5:
                    continue
                killed += 1 + len(o.cargo)
                self.kill(o)
            self.fallout[c] = FALLOUT_TURNS
            hit = self.city(c)
            if hit is not None:
                hit.irradiated = IRRADIATED_TURNS
                hit.militia = 0
                hit.progress = 0.0
                if c == cell and hit.size > 1:
                    hit.size -= 1
        self.doomsday -= 3 if city else 2
        self.record("nuke", cell, f, name=place)
        self.log(Msg("☢ {faction} colpisce {place} con un'arma nucleare: {killed} unità "
                     "annientate. Orologio dell'Apocalisse: {minutes} min.",
                     faction=fac.name, place=place, killed=killed, minutes=max(0, self.doomsday)),
                 None, "wmd", "nuke", f)
        if victim is not None and victim != f:
            self.factions[victim].nuked_by.append(f)
        self._dirty()
        self._check_clock()
        return "hit"

    def can_chemical(self, f: int, cell: int) -> bool:
        if self.factions[f].chemicals <= 0:
            return False
        w = self.world
        return any(c.owner == f and w.dist(c.cell, cell) <= CHEM_RANGE for c in self.cities) or \
            any(u.owner == f and w.dist(u.cell, cell) <= CHEM_RANGE for u in self.units.values())

    # ------------------------------------------------------------------ space
    def launch_satellite(self, f: int, city: City) -> None:
        """A spy satellite goes up above the city that built it."""
        self.factions[f].satellites.append(city.cell % self.world.width)
        self._dirty()
        self.log(Msg("{faction} mette in orbita un satellite spia da {city}.",
                     faction=self.factions[f].name, city=city.name), None, "alert", "satellite", f)

    def satellite_band(self, column: int) -> range:
        """The columns a satellite above ``column`` watches."""
        return range(column - SATELLITE_SWATH, column + SATELLITE_SWATH + 1)

    def asat_strike(self, f: int, target: int) -> str:
        """Fire an anti-satellite weapon at one of ``target``'s satellites."""
        fac, victim = self.factions[f], self.factions[target]
        if fac.asats <= 0:
            return "noasat"
        if target == f or not self.hostile(f, target):
            return "truce" if target != f else "illegal"
        if not victim.satellites:
            return "nosat"
        fac.asats -= 1
        self.quiet_turns = 0
        if self.rng.random() >= ASAT_CHANCE:
            self.log(Msg("{faction} lancia un'arma antisatellite contro {target}: mancato.",
                         faction=fac.name, target=victim.name), None, "alert", "asat", f)
            return "missed"
        victim.satellites.pop(self.rng.randrange(len(victim.satellites)))
        self._dirty()
        self.log(Msg("{faction} abbatte un satellite spia di {target}: ne restano {left}.",
                     faction=fac.name, target=victim.name, left=len(victim.satellites)),
                 None, "alert", "asat", f)
        return "ok"

    def _orbit(self) -> None:
        """Every round each satellite moves on to watch another band."""
        for fac in self.factions:
            fac.satellites = [(x + SATELLITE_STEP) % self.world.width for x in fac.satellites]
        self._dirty()

    def chemical_strike(self, f: int, cell: int) -> str:
        if not self.can_chemical(f, cell) or self.over:
            return "illegal"
        city = self.city(cell)
        if city is not None and city.owner is not None and not self.hostile(f, city.owner):
            return "truce"
        fac = self.factions[f]
        fac.chemicals -= 1
        fac.used_wmd += 1
        self.quiet_turns = 0
        hurt = 0
        for c in self.world.ring(cell, 1):
            for o in self.units_at(c):
                for victim in [o] + [self.units[k] for k in o.cargo if o.type.domain == "land"]:
                    if victim.type.domain != "land" or victim.id not in self.units:
                        continue
                    hurt += 1
                    victim.hp -= 2
                    if victim.hp <= 0:
                        self.kill(victim)
            hit = self.city(c)
            if hit is not None:
                hit.militia //= 2
        self.doomsday -= 1
        city = self.city(cell)
        place = city.name if city else _coords(self.world, cell)
        self.record("chem", cell, f, name=place)
        self.log(Msg("☣ {faction} usa armi chimiche su {place}: {hurt} unità colpite. "
                     "Orologio dell'Apocalisse: {minutes} min.",
                     faction=fac.name, place=place, hurt=hurt, minutes=max(0, self.doomsday)),
                 None, "wmd", "gas", f)
        self._check_clock()
        return "hit"

    # -------------------------------------------------------------- diplomacy
    @staticmethod
    def _pair(a: int, b: int) -> str:
        return f"{min(a, b)}-{max(a, b)}"

    def truce_left(self, a: int, b: int) -> int:
        end = self.truces.get(self._pair(a, b))
        return max(0, end - self.turn + 1) if end is not None else 0

    def hostile(self, a: int | None, b: int | None) -> bool:
        """At war? Neutrals are always fair game; truce partners are not."""
        if a == b:
            return False
        if a is None or b is None:
            return True
        return self.truce_left(a, b) == 0

    def proposals_to(self, f: int) -> list[int]:
        return [a for a, b in self.proposals if b == f]

    def propose_truce(self, f: int, target: int) -> str:
        if not self.factions[target].alive or self.truce_left(f, target):
            return "illegal"
        if [f, target] in self.proposals:
            return "pending"
        if [target, f] in self.proposals:
            return self.answer_truce(f, target, True)
        key = f"{f}>{target}"
        if self.turn - self.offered.get(key, -99) < 5:
            return "cooldown"
        self.offered[key] = self.turn
        if self.factions[target].human:
            self.proposals.append([f, target])
            self.log(Msg("{faction} propone una tregua di {turns} turni.",
                         faction=self.factions[f].name, turns=TRUCE_TURNS),
                     [f, target], "alert", "truce", f)
            return "pending"
        from theempire.ai import accepts_truce
        if accepts_truce(self, target, f):
            self._make_truce(f, target)
            return "accepted"
        self.log(Msg("{faction} respinge la proposta di tregua di {proposer}.",
                     faction=self.factions[target].name, proposer=self.factions[f].name), [f, target])
        return "refused"

    def answer_truce(self, f: int, proposer: int, accept: bool) -> str:
        if [proposer, f] not in self.proposals:
            return "illegal"
        self.proposals.remove([proposer, f])
        if accept:
            self._make_truce(f, proposer)
            return "accepted"
        self.log(Msg("{faction} respinge la tregua proposta da {proposer}.",
                     faction=self.factions[f].name, proposer=self.factions[proposer].name), [f, proposer])
        return "refused"

    def _make_truce(self, a: int, b: int) -> None:
        self.truces[self._pair(a, b)] = self.turn + TRUCE_TURNS
        self.proposals = [p for p in self.proposals if set(p) != {a, b}]
        self.log(Msg("Tregua di {turns} turni tra {a} e {b}.", turns=TRUCE_TURNS,
                     a=self.factions[a].name, b=self.factions[b].name), None, "alert", "truce")
        self._dirty()

    def _check_clock(self) -> None:
        if self.doomsday <= 0 and not self.over:
            self.over = (None, "armageddon")
            self.log(Msg("MEZZANOTTE. La guerra nucleare totale ha distrutto la civiltà. "
                         "Nessuno ha vinto."), None, "wmd")

    # ------------------------------------------------------------------ turns
    @property
    def realtime(self) -> int:
        """Seconds between two pulses of a real-time game (0: turn-based)."""
        return self.options.get("realtime", 0)

    @property
    def faction(self) -> Faction:
        return self.factions[self.current]

    def production_rate(self, c: City) -> float:
        if c.owner is None or c.irradiated:
            return 0.0
        fac = self.factions[c.owner]
        rate = (c.size + (1 if c.capital else 0)) * fac.industry
        if not fac.human:
            rate *= DIFFICULTY.get(self.difficulty, 1.0)
        if c.unrest:
            rate *= 0.5
        if cards.active(self, c.owner, "plan"):
            rate *= 1.5
        rate *= 1 + regions.production_bonus(self, c.owner)
        if events.active(self, "boom"):
            rate *= 1.25
        if events.active(self, "famine") and c.size >= 3:
            rate *= 0.7
        return rate

    def can_build(self, c: City, key: str) -> bool:
        if key in MODERN and not self.scenario.modern:
            return False
        if key == SATELLITE:
            return c.owner is not None and (c.size >= 3 or c.capital)
        if key == ASAT:
            return c.owner is not None and c.size >= 2
        if key == WARHEAD:
            return c.owner is not None and self.factions[c.owner].nuclear and c.size >= 2
        if key == CHEMICAL:
            return c.owner is not None
        t = UNIT_TYPES.get(key)
        if t is None:
            return False
        return t.domain != "sea" or self.is_port(c.cell)

    def directive_choice(self, c: City, directive: str) -> str | None:
        """What a city builds under a directive (None: leave it alone)."""
        big, port, k = c.size >= 2, self.is_port(c.cell), c.id
        troops = "A" if big and k % 3 else "I"
        choice = {
            "land": troops,
            "defense": "I",
            "air": "B" if big and k % 3 == 0 else "F",
            "sea": ("C" if big and k % 7 == 0 else "DSR"[k % 3]) if port else troops,
            "amphibious": ("T" if k % 2 == 0 else troops) if port else troops,
            "nuclear": WARHEAD if c.capital or c.size == 3 else troops,
        }.get(directive)
        if choice is None:
            return None
        return choice if self.can_build(c, choice) else troops if self.can_build(c, troops) else "I"

    def apply_directive(self, f: int) -> int:
        """Set every city of ``f`` not chosen by hand to the faction's
        directive. Progress already made carries over. Returns the cities
        changed."""
        directive = self.factions[f].directive
        changed = 0
        for c in self.cities:
            if c.owner != f or c.manual:
                continue
            choice = self.directive_choice(c, directive)
            if choice is not None and choice != c.production:
                c.production = choice
                changed += 1
        return changed

    def begin_turn(self) -> None:
        f = self.current
        fac = self.factions[f]
        regions.update(self)
        if self.turn % cards.BRIEFING_EVERY == 0:
            cards.draw(self, f, N("Rapporto dei servizi segreti"))
        room = self.supply_limit(f) - len(self.units_of(f))
        for c in self.cities:
            if c.owner != f:
                continue
            if c.irradiated:
                c.irradiated -= 1
            if c.unrest:
                c.unrest -= 1
            c.militia = min(c.militia_max(), c.militia + 1)
            if not self.can_build(c, c.production):
                c.production = "I"
            c.progress += self.production_rate(c)
            cost = production_cost(c.production)
            if c.progress >= cost and c.production in UNIT_TYPES and room <= 0:
                c.progress = float(cost)   # supply limit reached: wait
                continue
            if c.progress >= cost:
                c.progress -= cost
                if c.production == WARHEAD:
                    fac.warheads += 1
                    self.log(Msg("{city} ha prodotto una testata nucleare.", city=c.name), [f])
                elif c.production == CHEMICAL:
                    fac.chemicals += 1
                    self.log(Msg("{city} ha prodotto armi chimiche.", city=c.name), [f])
                elif c.production == SATELLITE:
                    self.launch_satellite(f, c)
                elif c.production == ASAT:
                    fac.asats += 1
                    self.log(Msg("{city} ha prodotto un'arma antisatellite.", city=c.name), [f])
                else:
                    room -= 1
                    self.create_unit(c.production, f, c.cell)
                    self.log(Msg("{city} ha prodotto: {unit}.", city=c.name,
                                 unit=UNIT_TYPES[c.production].name), [f])
        oil, winter = events.active(self, "oil"), events.active(self, "winter")
        for u in list(self.units_of(f)):
            t = u.type
            u.moves = t.move
            if oil and t.domain in ("air", "sea"):
                u.moves = max(1, (t.move + 1) // 2)
            if winter and t.domain == "land" and self.world.lonlat(u.cell)[1] > 45:
                u.moves = max(1, t.move - 1)
            city = self.city(u.cell)
            in_base = (city is not None and city.owner == f) or u.carrier is not None
            if city is not None and city.owner == f and u.hp < t.hp:
                u.hp += 1
            if t.domain == "air" and in_base:
                u.fuel = t.fuel
            if self.fallout.get(u.cell) and t.domain == "land" and city is None:
                u.hp -= 1
                if u.hp <= 0:
                    self.log(Msg("{unit} ucciso dalle radiazioni.", unit=t.name), [f], "combat", "loss", f)
                    self.kill(u)
        self._dirty()

    def end_turn(self) -> None:
        """Finish the current faction's turn and start the next living one."""
        if self.over:
            return
        cards.end_of_turn(self, self.current)
        regions.update(self)
        self._check_victory()
        n = len(self.factions)
        for _ in range(n):
            self.current = (self.current + 1) % n
            if self.current == 0:
                self._new_round()
                if self.over:
                    return
            if self.factions[self.current].alive:
                break
        self.begin_turn()

    def _new_round(self) -> None:
        self.turn += 1
        self.quiet_turns += 1
        for c in self.cities:  # neutral cities slowly rebuild their militia
            if c.owner is None:
                c.militia = min(c.militia_max(), c.militia + 1)
        for c in list(self.fallout):
            self.fallout[c] -= 1
            if self.fallout[c] <= 0:
                del self.fallout[c]
        if self.quiet_turns >= CLOCK_RECOVERY_TURNS and self.doomsday < self.scenario.doomsday:
            self.doomsday += 1
            self.quiet_turns = 0
            self.log(Msg("La tensione cala: Orologio dell'Apocalisse a {minutes} minuti.",
                         minutes=self.doomsday))
        for pair, end in list(self.truces.items()):
            if end < self.turn:
                del self.truces[pair]
                a, b = (int(x) for x in pair.split("-"))
                self.log(Msg("La tregua tra {a} e {b} è scaduta: si torna a combattere.",
                             a=self.factions[a].name, b=self.factions[b].name), None, "alert", "alert")
        self._orbit()
        events.new_round(self)
        regions.update(self)
        self._check_victory()
        if not self.over and self.turn > self.scenario.max_turns:
            best = max((f for f in self.factions if f.alive), key=self.score)
            self.over = (best.idx, "turns")
            self.log(Msg("Fine delle ostilità: {faction} vince ai punti.", faction=best.name),
                     None, "alert")

    def score(self, f: Faction) -> int:
        cities = sum(c.size * 10 for c in self.cities if c.owner == f.idx)
        army = sum(u.type.cost for u in self.units.values() if u.owner == f.idx) // 4
        return cities + army + f.warheads * 2

    def _check_victory(self) -> None:
        if self.over:
            return
        for f in self.factions:
            if f.alive and not self.cities_of(f.idx):
                self.eliminate(f.idx)
        alive = [f for f in self.factions if f.alive]
        if len(alive) == 1:
            self.over = (alive[0].idx, "conquest")
            self.log(Msg("{faction} ha sconfitto tutti i rivali!", faction=alive[0].name),
                     None, "alert")
            return
        if any(f.human for f in self.factions) and not any(f.alive for f in self.factions if f.human):
            winner = max(alive, key=self.score)
            self.over = (winner.idx, "conquest")
            self.log(Msg("Il tuo governo è caduto. Hai perso la guerra."), None, "alert")
            return
        # a secret objective: the faction playing is checked first
        for f in sorted(alive, key=lambda f: f.idx != self.current):
            if f.mission and missions.done(self, f.idx):
                self.over = (f.idx, "mission")
                self.log(Msg("{faction} ha completato il suo obiettivo segreto: {mission}",
                             faction=f.name, mission=missions.message(self, f.idx)), None, "alert")
                return
        total = len(self.cities)
        for f in alive:
            if len(self.cities_of(f.idx)) >= self.scenario.victory_share * total:
                self.over = (f.idx, "domination")
                self.log(Msg("{faction} controlla il {pct}% delle città del mondo: dominio globale!",
                             faction=f.name, pct=int(self.scenario.victory_share * 100)),
                         None, "alert")
                return

    # ------------------------------------------------------------- save/load
    def to_dict(self) -> dict:
        state = self.rng.getstate()
        return {
            "version": 1,
            "scenario": self.scenario.key,
            "difficulty": self.difficulty,
            "options": self.options,
            "turn": self.turn, "current": self.current,
            "doomsday": self.doomsday, "quiet_turns": self.quiet_turns,
            "fallout": [[k, v] for k, v in self.fallout.items()],
            "over": list(self.over) if self.over else None,
            "truces": self.truces, "proposals": self.proposals, "prepared": self.prepared,
            "offered": self.offered,
            "next_id": self.next_id,
            "rng": [state[0], list(state[1]), state[2]],
            "event_seq": self.event_seq,
            "deck": self.deck, "discard": self.discard,
            "world_effects": self.world_effects, "next_event": self.next_event,
            "factions": [asdict(f) for f in self.factions],
            "cities": [asdict(c) for c in self.cities],
            "units": [asdict(u) for u in self.units.values()],
            "events": [asdict(e) for e in self.events[-60:]],
        }

    @classmethod
    def from_dict(cls, d: dict, world: World | None = None) -> "Game":
        g = cls(d["scenario"], difficulty=d["difficulty"], world=world, _empty=True,
                hexgrid=bool(d.get("options", {}).get("hex")))
        g.options.update(d.get("options", {}))
        g.turn, g.current = d["turn"], d["current"]
        g.doomsday, g.quiet_turns = d["doomsday"], d["quiet_turns"]
        g.fallout = {int(k): v for k, v in d["fallout"]}
        g.over = tuple(d["over"]) if d["over"] else None
        g.truces = dict(d.get("truces", {}))
        g.proposals = [list(p) for p in d.get("proposals", [])]
        g.prepared = d.get("prepared")
        g.offered = dict(d.get("offered", {}))
        g.next_id = d["next_id"]
        r = d["rng"]
        g.rng.setstate((r[0], tuple(r[1]), r[2]))
        g.factions = [Faction(**f) for f in d["factions"]]
        g.cities = [City(**c) for c in d["cities"]]
        g.city_at = {c.cell: c.id for c in g.cities}
        for ud in d["units"]:
            u = Unit(**ud)
            g.units[u.id] = u
            if u.carrier is None:
                g.at.setdefault(u.cell, []).append(u.id)
        g.events = [Event(**e) for e in d["events"]]
        g.event_seq = d.get("event_seq", len(g.events))
        g.world_effects = dict(d.get("world_effects", {}))
        g.next_event = d.get("next_event", 0)
        regions.update(g)               # who holds what (no announcement)
        g.deck = list(d.get("deck", []))
        g.discard = list(d.get("discard", []))
        if not g.deck and not g.discard and not any(f.cards for f in g.factions):
            g.deck = cards.new_deck(g.rng)   # a save from before the cards
        return g

    def save_file(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @classmethod
    def load_file(cls, path: Path) -> "Game":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------- combat
def fight(a: float, ahp: int, d: float, dhp: int, rng: random.Random) -> tuple[int, int]:
    """A duel: each round one side loses a hit point."""
    p = a / (a + d) if a + d > 0 else 0.5
    while ahp > 0 and dhp > 0:
        if rng.random() < p:
            dhp -= 1
        else:
            ahp -= 1
    return ahp, dhp


def win_probability(a: float, ahp: int, d: float, dhp: int) -> float:
    p = a / (a + d) if a + d > 0 else 0.5
    return _win(round(p, 4), ahp, dhp)


@lru_cache(maxsize=4096)
def _win(p: float, ahp: int, dhp: int) -> float:
    if dhp <= 0:
        return 1.0
    if ahp <= 0:
        return 0.0
    return p * _win(p, ahp, dhp - 1) + (1 - p) * _win(p, ahp - 1, dhp)


def _coords(world: World, cell: int) -> str:
    lon, lat = world.lonlat(cell)
    return f"{abs(lat):.0f}°{'N' if lat >= 0 else 'S'} {abs(lon):.0f}°{'E' if lon >= 0 else 'W'}"
