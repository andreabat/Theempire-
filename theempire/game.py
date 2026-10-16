"""Game rules: units, cities, movement, combat, production, WMD and victory.

The rules follow Empire (one unit per cell outside cities, cities build one
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

from theempire.scenarios import SCENARIOS, Scenario
from theempire.units import (CHEMICAL, UNIT_TYPES, WARHEAD, UnitType,
                             production_cost)
from theempire.world import World, load_world

DIFFICULTY = {"facile": 0.75, "normale": 1.0, "difficile": 1.3}
FALLOUT_TURNS = 12
IRRADIATED_TURNS = 10
UNREST_TURNS = 5
CHEM_RANGE = 4
MILITIA_ATTACK, MILITIA_DEFENSE = 1, 1
CITY_DEFENSE_BONUS = 1.5
FORTIFY_BONUS = 1.25
SUPPORT_BONUS = 0.15                # per friendly land unit next to the target
SUPPORT_MAX = 4
SUPPLY_FACTOR = 1.6                 # unit cap = factor x base production + 20
CLOCK_RECOVERY_TURNS = 6


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


@dataclass
class Event:
    turn: int
    text: str
    audience: list[int] | None = None   # None = everybody
    level: str = "info"                 # info | combat | alert | wmd


class Game:
    def __init__(self, scenario: str = "ww3", humans: tuple[str, ...] = (),
                 difficulty: str = "normale", seed: int | None = None,
                 world: World | None = None, _empty: bool = False):
        self.world = world or load_world()
        self.scenario: Scenario = SCENARIOS[scenario]
        self.difficulty = difficulty
        self.rng = random.Random(seed)
        self.turn = 1
        self.current = 0
        self.doomsday = self.scenario.doomsday
        self.quiet_turns = 0
        self.fallout: dict[int, int] = {}
        self.events: list[Event] = []
        self.over: tuple[int | None, str] | None = None
        self.units: dict[int, Unit] = {}
        self.at: dict[int, list[int]] = {}
        self.next_id = 1
        self._vis: dict[int, set[int]] = {}
        self.factions: list[Faction] = []
        self.cities: list[City] = []
        self.city_at: dict[int, int] = {}
        if _empty:
            return
        for k, fd in enumerate(self.scenario.factions):
            self.factions.append(Faction(
                k, fd.key, fd.name, fd.color, fd.key in humans, fd.doctrine,
                fd.warheads, fd.chemicals, fd.abm, fd.nuclear, fd.industry))
        owner_of_iso = {iso: k for k, fd in enumerate(self.scenario.factions) for iso in fd.countries}
        for site in self.world.sites:
            owner = owner_of_iso.get(site.iso)
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
        self.log(f"{self.scenario.name}: la guerra è cominciata. Orologio dell'Apocalisse "
                 f"a {self.doomsday} minuti dalla mezzanotte.", level="alert")
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
    def log(self, text: str, audience: list[int] | None = None, level: str = "info") -> None:
        self.events.append(Event(self.turn, text, audience, level))
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
        return "Neutrali" if owner is None else self.factions[owner].name

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
            self._vis[f] = vis
        return vis

    def sees(self, f: int, u: Unit) -> bool:
        if u.owner == f:
            return True
        if u.cell not in self.visible(f):
            return False
        if u.type.stealth and u.carrier is None:
            return any(self.world.dist(u.cell, o.cell) <= (2 if o.kind == "D" else 1)
                       for o in self.units.values() if o.owner == f and o.carrier is None) \
                or any(c.owner == f and self.world.dist(u.cell, c.cell) <= 1 for c in self.cities)
        return True

    def _dirty(self) -> None:
        self._vis.clear()

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
    def terrain_ok(self, kind: str, cell: int, owner: int) -> bool:
        """Can a unit of this kind stand on this cell (ignoring other units)?"""
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
        hostile_city = city is not None and city.owner != u.owner
        enemies = [o for o in others if o.owner != u.owner]
        if enemies or hostile_city:
            return "attack" if self.can_attack(u, cell) else None
        if city is not None:  # own city
            if t.domain == "sea" and not self.is_port(cell):
                return None
            return "move"
        if others:
            o = others[0]
            if t.domain == "land" and o.type.carries == "land" and self.has_room(o):
                return "board"
            if t.domain == "air" and o.type.carries == "air" and self.has_room(o):
                return "board"
            return None
        return "move" if self.terrain_ok(u.kind, cell, u.owner) else None

    def can_attack(self, u: Unit, cell: int) -> bool:
        t = u.type
        if t.attack <= 0:
            return False
        city = self.city(cell)
        targets = [o for o in self.units_at(cell) if o.owner != u.owner]
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
            hidden = [o for o in self.units_at(cell) if o.owner != u.owner and not self.sees(u.owner, o)]
            if hidden:
                self.log(f"{u.type.name}: contatto con un'unità nascosta!", [u.owner], "combat")
                u.moves = 0
                self._dirty()
                return "blocked"
            return "illegal"
        if action == "attack":
            return self.attack(u, cell)
        self._spend(u)
        if action == "board":
            carrier = self.units_at(cell)[0]
            self._embark(u, carrier)
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
            self.log(f"Un {u.type.name.lower()} è rimasto senza carburante ed è precipitato.",
                     [u.owner], "combat")
            self.kill(u)

    def _wake_sentries(self, mover: Unit) -> None:
        """Enemy units on sentry duty wake up when ``mover`` comes close."""
        for o in self.units.values():
            if o.owner != mover.owner and o.order == "sentry" and o.carrier is None \
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
            if avoid_units and c in self.at and city is None:
                return False
            return True

        if not passable(dest) and domain != "air":
            return None
        if domain == "land" and not w.land[dest]:
            return None
        frontier = [(w.dist(start, dest), 0, start)]
        came = {start: None}
        cost = {start: 0}
        expanded = 0
        while frontier:
            _, g, c = heapq.heappop(frontier)
            if c == dest:
                break
            expanded += 1
            if expanded > limit:
                return None
            for n in w.neighbors[c]:
                if n in cost or not passable(n):
                    continue
                cost[n] = g + 1
                came[n] = c
                heapq.heappush(frontier, (g + 1 + w.dist(n, dest), g + 1, n))
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
                self.log(f"{u.type.name}: destinazione irraggiungibile.", [u.owner])
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
        enemies = [o for o in self.units_at(cell) if o.owner != attacker.owner]
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
        city = self.city(cell)
        d = self.defender_at(u, cell)
        av = self.attack_value(u, cell, d)
        self._spend(u)
        if u.type.domain == "land" and u.carrier is not None:
            u.moves = 0
        u.order = None
        if d is not None:
            dv = self.defense_value(u, d)
            ahp, dhp = fight(av, u.hp, dv, d.hp, self.rng)
            where = f" presso {city.name}" if city else ""
            if ahp > 0:
                u.hp = ahp
                self.factions[u.owner].kills += 1
                self.log(f"{self.factions[u.owner].name}: {u.type.name} distrugge "
                         f"{d.type.name}{where} ({self.faction_name(d.owner)}).",
                         [u.owner, d.owner], "combat")
                self.kill(d)
                result = "won"
            else:
                d.hp = dhp
                self.factions[d.owner].kills += 1
                self.log(f"{self.factions[u.owner].name}: {u.type.name} distrutto attaccando "
                         f"{d.type.name}{where} ({self.faction_name(d.owner)}).",
                         [u.owner, d.owner], "combat")
                self.kill(u)
                return "lost"
        elif city is not None:
            defender_owner = city.owner
            ahp, mhp = fight(av, u.hp, MILITIA_DEFENSE * CITY_DEFENSE_BONUS, max(1, city.militia), self.rng)
            if ahp <= 0:
                city.militia = max(1, mhp)
                self.log(f"{u.type.name} ({self.factions[u.owner].name}) respinto dalla "
                         f"milizia di {city.name}.",
                         [u.owner] + ([defender_owner] if defender_owner is not None else []), "combat")
                self.kill(u)
                return "lost"
            u.hp = ahp
            city.militia = 0
            if u.type.capture:
                self.capture(city, u)
                return "captured"
            self.log(f"{city.name}: le difese sono a terra, serve la fanteria per occuparla.",
                     [u.owner])
            result = "won"
        else:
            return "illegal"
        if u.type.domain == "air":
            self._air_after_move(u)
        self._dirty()
        return result

    def capture(self, city: City, u: Unit) -> None:
        old = city.owner
        city.owner = u.owner
        city.progress = 0.0
        city.unrest = UNREST_TURNS
        city.militia = 1
        city.production = self._default_production(city)
        self._detach(u)
        self._place(u, city.cell)
        u.moves = 0
        audience = None
        tag = "CAPITALE " if city.capital else ""
        self.log(f"{self.factions[u.owner].name} conquista {tag}{city.name} "
                 f"(prima: {self.faction_name(old)}).", audience, "alert" if city.capital or old is not None else "info")
        if old is not None and not self.cities_of(old):
            self.eliminate(old)
        self._dirty()

    def eliminate(self, f: int) -> None:
        fac = self.factions[f]
        if not fac.alive:
            return
        fac.alive = False
        for u in self.units_of(f):
            if u.id in self.units:
                self.kill(u)
        self.log(f"{fac.name} ha perso l'ultima città ed è fuori dalla guerra.", None, "alert")

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
        place = city.name if city else _coords(w, cell)
        if victim is not None and victim != f and self.rng.random() < self.factions[victim].abm:
            self.doomsday -= 1
            self.log(f"☢ {fac.name} lancia un missile nucleare su {place}: intercettato "
                     f"dalla difesa antimissile di {self.factions[victim].name}!", None, "wmd")
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
        self.log(f"☢ {fac.name} colpisce {place} con un'arma nucleare: {killed} unità "
                 f"annientate. Orologio dell'Apocalisse: {max(0, self.doomsday)} min.", None, "wmd")
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

    def chemical_strike(self, f: int, cell: int) -> str:
        if not self.can_chemical(f, cell) or self.over:
            return "illegal"
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
        self.log(f"☣ {fac.name} usa armi chimiche su {place}: {hurt} unità colpite. "
                 f"Orologio dell'Apocalisse: {max(0, self.doomsday)} min.", None, "wmd")
        self._check_clock()
        return "hit"

    def _check_clock(self) -> None:
        if self.doomsday <= 0 and not self.over:
            self.over = (None, "armageddon")
            self.log("MEZZANOTTE. La guerra nucleare totale ha distrutto la civiltà. "
                     "Nessuno ha vinto.", None, "wmd")

    # ------------------------------------------------------------------ turns
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
        return rate

    def can_build(self, c: City, key: str) -> bool:
        if key == WARHEAD:
            return c.owner is not None and self.factions[c.owner].nuclear and c.size >= 2
        if key == CHEMICAL:
            return c.owner is not None
        t = UNIT_TYPES.get(key)
        if t is None:
            return False
        return t.domain != "sea" or self.is_port(c.cell)

    def begin_turn(self) -> None:
        f = self.current
        fac = self.factions[f]
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
                    self.log(f"{c.name} ha prodotto una testata nucleare.", [f])
                elif c.production == CHEMICAL:
                    fac.chemicals += 1
                    self.log(f"{c.name} ha prodotto armi chimiche.", [f])
                else:
                    room -= 1
                    self.create_unit(c.production, f, c.cell)
                    self.log(f"{c.name} ha prodotto: {UNIT_TYPES[c.production].name}.", [f])
        for u in list(self.units_of(f)):
            t = u.type
            u.moves = t.move
            city = self.city(u.cell)
            in_base = (city is not None and city.owner == f) or u.carrier is not None
            if city is not None and city.owner == f and u.hp < t.hp:
                u.hp += 1
            if t.domain == "air" and in_base:
                u.fuel = t.fuel
            if self.fallout.get(u.cell) and t.domain == "land" and city is None:
                u.hp -= 1
                if u.hp <= 0:
                    self.log(f"{t.name} ucciso dalle radiazioni.", [f], "combat")
                    self.kill(u)
        self._dirty()

    def end_turn(self) -> None:
        """Finish the current faction's turn and start the next living one."""
        if self.over:
            return
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
            self.log(f"La tensione cala: Orologio dell'Apocalisse a {self.doomsday} minuti.")
        self._check_victory()
        if not self.over and self.turn > self.scenario.max_turns:
            best = max((f for f in self.factions if f.alive), key=self.score)
            self.over = (best.idx, "turns")
            self.log(f"Fine delle ostilità: {best.name} vince ai punti.", None, "alert")

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
            self.log(f"{alive[0].name} ha sconfitto tutti i rivali!", None, "alert")
            return
        if any(f.human for f in self.factions) and not any(f.alive for f in self.factions if f.human):
            winner = max(alive, key=self.score)
            self.over = (winner.idx, "conquest")
            self.log("Il tuo governo è caduto. Hai perso la guerra.", None, "alert")
            return
        total = len(self.cities)
        for f in alive:
            if len(self.cities_of(f.idx)) >= self.scenario.victory_share * total:
                self.over = (f.idx, "domination")
                self.log(f"{f.name} controlla il {int(self.scenario.victory_share * 100)}% delle "
                         "città del mondo: dominio globale!", None, "alert")
                return

    # ------------------------------------------------------------- save/load
    def to_dict(self) -> dict:
        state = self.rng.getstate()
        return {
            "version": 1,
            "scenario": self.scenario.key,
            "difficulty": self.difficulty,
            "turn": self.turn, "current": self.current,
            "doomsday": self.doomsday, "quiet_turns": self.quiet_turns,
            "fallout": [[k, v] for k, v in self.fallout.items()],
            "over": list(self.over) if self.over else None,
            "next_id": self.next_id,
            "rng": [state[0], list(state[1]), state[2]],
            "factions": [asdict(f) for f in self.factions],
            "cities": [asdict(c) for c in self.cities],
            "units": [asdict(u) for u in self.units.values()],
            "events": [asdict(e) for e in self.events[-60:]],
        }

    @classmethod
    def from_dict(cls, d: dict, world: World | None = None) -> "Game":
        g = cls(d["scenario"], difficulty=d["difficulty"], world=world, _empty=True)
        g.turn, g.current = d["turn"], d["current"]
        g.doomsday, g.quiet_turns = d["doomsday"], d["quiet_turns"]
        g.fallout = {int(k): v for k, v in d["fallout"]}
        g.over = tuple(d["over"]) if d["over"] else None
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
        return g

    def save_file(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @classmethod
    def load_file(cls, path: Path) -> "Game":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------- combat
def fight(a: float, ahp: int, d: float, dhp: int, rng: random.Random) -> tuple[int, int]:
    """Empire-style duel: each round one side loses a hit point."""
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
