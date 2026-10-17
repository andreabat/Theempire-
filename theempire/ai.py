"""Computer opponents.

The AI works from shared distance fields computed once per turn (multi-source
breadth-first searches), so every unit only has to look at its neighbours:

* land units walk down the field that starts at hostile cities;
* land units with nothing to conquer on their continent walk to a port and
  wait for a transport;
* transports carry them to the coast next to a hostile city and unload;
* warships hunt visible ships and otherwise close in on enemy coasts;
* aircraft strike targets they can reach and still fly home from.

Escalation follows the faction's doctrine: everyone retaliates when hit
(mutually assured destruction), aggressive factions go nuclear first when
they are losing, and all of them hold back as the Doomsday Clock nears
midnight.
"""

from __future__ import annotations

import math

from theempire.game import Game, Unit
from theempire.units import UNIT_TYPES, WARHEAD

FIRST_STRIKE = {"aggressive": 0.25, "balanced": 0.12, "restrained": 0.05}
RETALIATE = {"aggressive": 0.95, "balanced": 0.8, "restrained": 0.65}
CHEMICAL_USE = {"aggressive": 0.06, "balanced": 0.03, "restrained": 0.0}
FAR_BY_LAND = 30
TRUCE_OFFER = {"aggressive": 0.03, "balanced": 0.06, "restrained": 0.1}
ATTACK_ODDS = {"aggressive": 0.45, "balanced": 0.5, "restrained": 0.55}


class AI:
    def __init__(self, game: Game, faction: int):
        self.g = game
        self.f = faction
        self.fac = game.factions[faction]
        self.w = game.world

    # ------------------------------------------------------------------ main
    def play(self) -> None:
        g = self.g
        self.min_odds = ATTACK_ODDS.get(self.fac.doctrine, 0.55)
        self._fields()
        self._garrisons()
        self.escalation()
        if g.over:
            return
        self.diplomacy()
        self.production()
        units = sorted(g.units_of(self.f), key=lambda u: "FBTSDRCAI".find(u.kind))
        for u in units:
            if g.over:
                return
            if u.id in g.units and u.carrier is None:
                self.act(u)
        # Fighters riding carriers may launch strikes too.
        for u in list(g.units_of(self.f)):
            if u.id in g.units and u.carrier is not None and u.type.domain == "air":
                self.air(u)

    def act(self, u: Unit) -> None:
        domain = u.type.domain
        if domain == "air":
            self.air(u)
        elif u.kind == "T":
            self.transport(u)
        elif domain == "sea":
            self.warship(u)
        else:
            self.land(u)

    def assist(self) -> None:
        """Run the human player's delegated work: automated units and,
        if enabled, city production."""
        g = self.g
        self.min_odds = ATTACK_ODDS["balanced"]
        auto = [u for u in g.units_of(self.f) if u.order == "auto"]
        if not auto and not self.fac.auto_production:
            return
        self._fields()
        if self.fac.auto_production:
            self.production()
        for u in sorted(auto, key=lambda u: "FBTSDRCAI".find(u.kind)):
            if g.over or u.id not in g.units:
                continue
            if u.carrier is not None and u.type.domain == "land":
                continue  # the transport decides where it lands
            u.order = None
            self.act(u)
            if u.id in g.units:
                u.order = "auto"

    # --------------------------------------------------------------- fields
    def _hostile_city_cells(self) -> list[int]:
        return [c.cell for c in self.g.cities if self.g.hostile(self.f, c.owner)]

    def _fields(self) -> None:
        g, w = self.g, self.w
        land = w.land
        hostile = self._hostile_city_cells()
        self.land_field = w.bfs(hostile, lambda c: land[c] and (
            g.city(c) is None or g.city(c).owner == self.f))
        my_ports = [c.cell for c in g.cities_of(self.f) if g.is_port(c.cell)]
        self.port_field = w.bfs(my_ports, lambda c: bool(land[c]))
        # Where transports should go: sea next to land close to a target.
        near_target = {c for c, d in self.land_field.items() if d <= 2}
        landing = {n for c in near_target for n in w.neighbors[c] if not land[n]}
        self.landing = landing
        sea_ok = self._sea_passable
        self.landing_field = w.bfs(landing, sea_ok)
        enemy_ports = [n for c in g.cities if c.owner is not None and g.hostile(self.f, c.owner)
                       for n in w.neighbors[c.cell] if not land[n]]
        self.enemy_coast_field = w.bfs(enemy_ports, sea_ok)
        self.home_sea_field = w.bfs(my_ports, sea_ok)
        waiting = [c for c in my_ports if any(
            u.type.domain == "land" and u.order == "sentry" for u in g.units_at(c) if u.owner == self.f)]
        self.pickup_field = w.bfs(waiting, sea_ok) if waiting else self.home_sea_field

    def _sea_passable(self, c: int) -> bool:
        if not self.w.land[c]:
            return True
        city = self.g.city(c)
        return city is not None and city.owner == self.f

    def _garrisons(self) -> None:
        """Keep a minimum garrison fortified in every city."""
        g, w = self.g, self.w
        enemy_cities = [c.cell for c in g.cities if c.owner is not None and g.hostile(self.f, c.owner)]
        vis = g.visible(self.f)
        enemy_units = [u.cell for u in g.units.values()
                       if g.hostile(self.f, u.owner) and u.carrier is None and u.cell in vis]
        for c in g.cities_of(self.f):
            threatened = any(w.dist(c.cell, e) <= 8 for e in enemy_cities) or \
                any(w.dist(c.cell, e) <= 4 for e in enemy_units)
            need = 1
            if threatened:
                need += (1 if c.size >= 2 else 0) + (1 if c.capital else 0)
            land_units = sorted((u for u in g.units_at(c.cell)
                                 if u.owner == self.f and u.type.domain == "land"),
                                key=lambda u: (u.kind != "I", u.id))
            for k, u in enumerate(land_units):
                if k < need:
                    u.order = "fortify"
                elif u.order == "fortify":
                    u.order = None

    # ------------------------------------------------------------ production
    def production(self) -> None:
        g = self.g
        mine = g.units_of(self.f)
        counts = {"land": 0, "air": 0, "sea": 0, "T": 0, "C": 0}
        for u in mine:
            counts[u.type.domain] += 1
            if u.kind in "TC":
                counts[u.kind] += 1
        ports = sum(1 for c in g.cities_of(self.f) if g.is_port(c.cell))
        stranded = sum(1 for u in mine if u.type.domain == "land" and self._needs_ship(u))
        total = max(1, len(mine))
        for c in g.cities_of(self.f):
            if c.manual and self.fac.human:
                continue  # the player chose this city's production by hand
            if c.progress >= g.production_rate(c) and g.can_build(c, c.production):
                continue  # keep building what is already under way
            port = g.is_port(c.cell)
            has_target = c.cell in self.land_field
            options: list[tuple[float, str]] = []
            land_share = counts["land"] / total
            options.append(((0.65 if has_target else 0.3) - land_share, "land"))
            options.append((0.12 - counts["air"] / total, "air"))
            if port:
                options.append((0.18 - (counts["sea"] - counts["T"]) / total, "navy"))
                want_t = math.ceil(stranded / 4)
                if want_t > counts["T"]:
                    options.append((0.5, "T"))
            if self.fac.nuclear and c.size >= 2 and self.fac.warheads < 4 and g.turn > 8:
                options.append((0.05 + (0.2 if c.capital else 0.0), WARHEAD))
            _, choice = max(options, key=lambda o: o[0] + g.rng.random() * 0.1)
            r = g.rng.random()
            if choice == "land":
                kind = "A" if c.size >= 2 and r < 0.55 else "I"
            elif choice == "air":
                kind = "F" if r < 0.45 else "B"
            elif choice == "navy":
                kind = "D" if r < 0.35 else "S" if r < 0.65 else "R"
                if r > 0.9 and counts["C"] < max(1, ports // 10):
                    kind = "C"
                    counts["C"] += 1
            else:
                kind = choice
            if g.can_build(c, kind):
                if kind != c.production:
                    c.production = kind
                if kind in UNIT_TYPES:
                    counts[UNIT_TYPES[kind].domain] += 1
                    if kind == "T":
                        counts["T"] += 1

    # ------------------------------------------------------------ escalation
    def escalation(self) -> None:
        g, fac = self.g, self.fac
        doctrine = fac.doctrine
        # Retaliation (MAD): answer every strike received since last turn.
        # A rational actor never makes the launch that ends the world,
        # unless it is about to be wiped out anyway.
        doomed = len(g.cities_of(self.f)) <= 3
        attackers = list(dict.fromkeys(fac.nuked_by))
        fac.nuked_by.clear()
        for enemy in attackers:
            p = RETALIATE.get(doctrine, 0.8)
            if g.doomsday <= 5 and doctrine != "aggressive":
                p /= 2
            if fac.warheads <= 0 or not g.factions[enemy].alive or g.rng.random() >= p:
                continue
            target = self._best_city(enemy)
            if target is not None and g.doomsday - 3 <= 0 and not doomed:
                target = self._best_tactical_target(owner=enemy, minimum=1)
                if g.doomsday - 2 <= 0:
                    target = None
            if target is not None:
                g.nuclear_strike(self.f, target)
                if g.over:
                    return
        if fac.warheads <= 0 and fac.chemicals <= 0:
            return
        # Desperation: heavy losses, the capital gone, or a rival about to
        # win by domination.
        threshold = 0.92 * g.scenario.victory_share * len(g.cities)
        rival_winning = any(len(g.cities_of(o.idx)) >= threshold
                            for o in g.factions if o.idx != self.f and o.alive)
        losing = rival_winning or len(g.cities_of(self.f)) < 0.6 * max(1, fac.start_cities) or not any(
            c.capital for c in g.cities_of(self.f))
        floor = 3 if doctrine == "aggressive" else 5
        if fac.warheads > 0 and losing and g.turn >= 5 and g.doomsday - 2 > floor \
                and g.rng.random() < FIRST_STRIKE.get(doctrine, 0.1):
            cell = self._best_tactical_target()
            if cell is not None:
                g.nuclear_strike(self.f, cell)
                return
        if fac.chemicals > 0 and g.doomsday > 3 and g.rng.random() < CHEMICAL_USE.get(doctrine, 0):
            cell = self._best_tactical_target(minimum=2, chemical=True)
            if cell is not None:
                g.chemical_strike(self.f, cell)

    def diplomacy(self) -> None:
        """Answer truce offers; offer one when the war is going badly."""
        g = self.g
        for proposer in g.proposals_to(self.f):
            g.answer_truce(self.f, proposer, accepts_truce(g, self.f, proposer))
        mine = len(g.cities_of(self.f))
        rivals = [o for o in g.factions if o.alive and o.idx != self.f and g.hostile(self.f, o.idx)]
        if len(rivals) < 2 and mine >= 0.6 * max(1, self.fac.start_cities):
            return  # alone against one rival and holding: fight on
        if not rivals or g.rng.random() >= TRUCE_OFFER.get(self.fac.doctrine, 0.05):
            return
        strongest = max(rivals, key=lambda o: len(g.cities_of(o.idx)))
        if len(g.cities_of(strongest.idx)) > mine:
            g.propose_truce(self.f, strongest.idx)

    def _best_city(self, enemy: int) -> int | None:
        cities = self.g.cities_of(enemy)
        if not cities:
            return None
        return max(cities, key=lambda c: (c.size + 2 * c.capital, -c.id)).cell

    def _best_tactical_target(self, minimum: int = 3, chemical: bool = False,
                              owner: int | None = None) -> int | None:
        """The visible enemy concentration close to our cities, never our own."""
        g, w = self.g, self.w
        vis = g.visible(self.f)
        enemies = [u for u in g.units.values() if g.hostile(self.f, u.owner) and u.carrier is None
                   and (owner is None or u.owner == owner)
                   and u.cell in vis and g.sees(self.f, u)]
        if not enemies:
            return None
        my_cities = g.cities_of(self.f)
        best, best_score = None, 0.0
        for u in enemies:
            if not any(w.dist(u.cell, c.cell) <= 5 for c in my_cities):
                continue
            cells = w.ring(u.cell, 1)
            if any(g.city(c) is not None and g.city(c).owner == self.f for c in cells):
                continue
            if any(o.owner == self.f for c in cells for o in g.units_at(c)):
                continue
            if chemical and not g.can_chemical(self.f, u.cell):
                continue
            if any(o.owner != self.f and not g.hostile(self.f, o.owner) for c in cells for o in g.units_at(c)):
                continue  # never hit a truce partner
            hit = [o for c in cells for o in g.units_at(c) if o.owner != self.f]
            if len(hit) < minimum:
                continue
            score = sum(o.type.cost + 10 * len(o.cargo) for o in hit)
            if score > best_score:
                best, best_score = u.cell, score
        return best

    # ------------------------------------------------------------ combat aid
    def _best_attack(self, u: Unit, cities_only: bool = False) -> int | None:
        g = self.g
        best, best_value = None, 0.0
        for n in self.w.neighbors[u.cell]:
            if g.classify(u, n) != "attack":
                continue
            city = g.city(n)
            if cities_only and city is None:
                continue
            defender = g.defender_at(u, n)
            if defender is not None and not g.sees(self.f, defender):
                continue
            p = g.odds(u, n)
            if p is None or p < self.min_odds:
                continue
            value = p * (1.0 + (3.0 * city.size if city is not None and u.type.capture else 0)
                         + (defender.type.cost / 10 if defender is not None else 0))
            if value > best_value:
                best, best_value = n, value
        return best

    def _step_down(self, u: Unit, field: dict[int, int], allow_board: bool = False) -> bool:
        """Move to the free neighbour with the lowest field value."""
        g = self.g
        here = field.get(u.cell, 10 ** 9)
        options = []
        for n in self.w.neighbors[u.cell]:
            d = field.get(n)
            if d is None or d >= here:
                continue
            action = g.classify(u, n)
            if action == "move" or (allow_board and action == "board"):
                options.append((d, g.rng.random(), n))
        if not options:
            return False
        g.move(u, min(options)[2])
        return True

    # ------------------------------------------------------------------ land
    def land(self, u: Unit) -> None:
        g = self.g
        if u.order == "fortify":
            target = self._best_attack(u)
            # Garrisons only strike out at weak neighbours.
            if target is not None and (g.odds(u, target) or 0) > 0.8:
                g.move(u, target)
            return
        while u.id in g.units and u.moves > 0 and u.carrier is None:
            target = self._best_attack(u)
            if target is not None:
                if g.move(u, target) in ("captured", "lost"):
                    return
                continue
            if u.cell in self.land_field and not self._needs_ship(u):
                if self.land_field[u.cell] == 1 and self._siege(u):
                    return
                if not self._step_down(u, self.land_field):
                    return
                continue
            # Nothing to conquer here: head for a port and wait for a ship.
            city = g.city(u.cell)
            if city is not None and city.owner == self.f and g.is_port(u.cell):
                for n in self.w.neighbors[u.cell]:
                    o = g.units_at(n)
                    if o and o[0].owner == self.f and o[0].kind == "T" and g.has_room(o[0]):
                        g.move(u, n)
                        return
                u.order = "sentry"
                return
            if not self._step_down(u, self.port_field, allow_board=True):
                return

    def _needs_ship(self, u: Unit) -> bool:
        """No target on this continent, or the nearest one is so far by land
        that a port close by is the quicker way to the war."""
        d = self.land_field.get(u.cell)
        if d is None:
            return True
        return d > FAR_BY_LAND and self.port_field.get(u.cell, 99) <= 6

    def _siege(self, u: Unit) -> bool:
        """Wear down a city's militia even at poor odds: damage persists."""
        g = self.g
        floor = 0.15 if self.fac.doctrine == "aggressive" else 0.25
        for n in self.w.neighbors[u.cell]:
            city = g.city(n)
            if city is None or city.owner == self.f or g.classify(u, n) != "attack":
                continue
            p = g.odds(u, n)
            if p is not None and p >= floor:
                g.move(u, n)
                return True
        return False

    # ------------------------------------------------------------ transports
    def transport(self, u: Unit) -> None:
        g = self.g
        city = g.city(u.cell)
        if city is not None and city.owner == self.f:
            g.load(u)
        loaded = len(u.cargo)
        guard = 0
        while u.id in g.units and u.moves > 0 and guard < 6:
            guard += 1
            if loaded and (loaded >= 3 or city is None or not self._more_waiting(u)):
                if u.cell in self.landing or self.landing_field.get(u.cell) == 0:
                    self._unload(u)
                    loaded = len(u.cargo)
                    if loaded:
                        return
                    continue
                if not self._step_down(u, self.landing_field):
                    return
            elif loaded:
                return  # wait in port for more troops
            else:
                field = self.pickup_field
                if field.get(u.cell) == 0:
                    return
                if not self._step_down(u, field):
                    return
            city = g.city(u.cell)
        if u.id in g.units and u.cargo and (u.cell in self.landing):
            self._unload(u)

    def _more_waiting(self, u: Unit) -> bool:
        return any(o.type.domain == "land" and o.order != "fortify"
                   for o in self.g.units_at(u.cell) if o.owner == self.f)

    def _unload(self, t: Unit) -> None:
        g = self.g
        for cid in list(t.cargo):
            cu = g.units.get(cid)
            if cu is None or cu.moves <= 0:
                continue
            target = self._best_attack(cu)
            if target is not None:
                g.move(cu, target)
                continue
            options = sorted(
                (self.land_field.get(n, 99), n) for n in self.w.neighbors[t.cell]
                if g.classify(cu, n) == "move" and self.w.land[n])
            if options:
                g.move(cu, options[0][1])

    # -------------------------------------------------------------- warships
    def warship(self, u: Unit) -> None:
        g = self.g
        guard = 0
        while u.id in g.units and u.moves > 0 and guard < 6:
            guard += 1
            if u.hp * 2 < u.type.hp:
                city = g.city(u.cell)
                if city is not None and city.owner == self.f:
                    return
                if not self._step_down(u, self.home_sea_field):
                    return
                continue
            if u.kind != "C":
                target = self._best_attack(u)
                if target is not None:
                    g.move(u, target)
                    continue
            prey = self._nearest_visible_ship(u, 8)
            if prey is not None:
                field = self.w.bfs([prey], self._sea_passable, limit=10)
                if self._step_down(u, field):
                    continue
            field = self.enemy_coast_field if u.kind != "C" else self.home_sea_field
            if field.get(u.cell, 99) <= (1 if u.kind != "C" else 2):
                return
            if not self._step_down(u, field):
                return

    def _nearest_visible_ship(self, u: Unit, radius: int) -> int | None:
        g, w = self.g, self.w
        best = None
        for o in g.units.values():
            if not g.hostile(self.f, o.owner) or o.carrier is not None or o.type.domain != "sea":
                continue
            d = w.dist(u.cell, o.cell)
            if d <= radius and g.sees(self.f, o) and g.city(o.cell) is None:
                if best is None or d < best[0]:
                    best = (d, o.cell)
        return best[1] if best else None

    # ------------------------------------------------------------------- air
    def _bases(self) -> list[int]:
        g = self.g
        out = [c.cell for c in g.cities_of(self.f)]
        out += [u.cell for u in g.units_of(self.f) if u.kind == "C" and u.carrier is None]
        return out

    def air(self, u: Unit) -> None:
        g, w = self.g, self.w
        bases = self._bases()
        if not bases:
            return
        guard = 0
        while u.id in g.units and u.moves > 0 and guard < 12:
            guard += 1
            at_base = u.carrier is not None or (g.city(u.cell) is not None and g.city(u.cell).owner == self.f)
            if at_base and u.fuel == u.type.fuel:
                target = self._air_target(u, bases)
                if target is None:
                    return
                if w.dist(u.cell, target) <= 1:
                    g.move(u, target)
                    continue
                if not self._fly_toward(u, target):
                    return
                continue
            # Out on a mission.
            target = self._best_attack(u)
            if target is not None:
                g.move(u, target)
                continue
            goal = self._air_target(u, bases) if u.fuel > u.type.fuel // 2 else None
            if goal is not None and w.dist(u.cell, goal) > 1:
                if self._fly_toward(u, goal):
                    continue
            home = min(bases, key=lambda b: w.dist(u.cell, b))
            if home == u.cell:
                return
            if not self._fly_toward(u, home, landing=True):
                return

    def _air_target(self, u: Unit, bases: list[int]) -> int | None:
        g, w = self.g, self.w
        best, best_value = None, 0.0
        reach = u.fuel
        vis = g.visible(self.f)
        for o in g.units.values():
            if not g.hostile(self.f, o.owner) or o.carrier is not None or o.kind == "S" or o.cell not in vis:
                continue
            d = w.dist(u.cell, o.cell)
            if d > reach or d + min(w.dist(o.cell, b) for b in bases) > reach - 1:
                continue
            defender = g.defender_at(u, o.cell)
            if defender is None:
                continue
            p = win_probability_for(g, u, o.cell, defender)
            if p < self.min_odds + 0.05:
                continue
            value = p * (defender.type.cost + 5 * len(defender.cargo)) / (1 + d / 4)
            if value > best_value:
                best, best_value = o.cell, value
        return best

    def _fly_toward(self, u: Unit, goal: int, landing: bool = False) -> bool:
        g, w = self.g, self.w
        here = w.dist(u.cell, goal)
        options = []
        for n in w.neighbors[u.cell]:
            d = w.dist(n, goal)
            if d >= here:
                continue
            action = g.classify(u, n)
            if action == "move" or (landing and action == "board"):
                options.append((d, g.rng.random(), n))
        if not options:
            return False
        g.move(u, min(options)[2])
        return True


def win_probability_for(g: Game, u: Unit, cell: int, defender: Unit) -> float:
    from theempire.game import win_probability
    return win_probability(g.attack_value(u, cell, defender), u.hp,
                           g.defense_value(u, defender), defender.hp)


def accepts_truce(g: Game, f: int, proposer: int) -> bool:
    """Would the AI faction ``f`` accept a truce offered by ``proposer``?"""
    fac = g.factions[f]
    if proposer in fac.nuked_by:
        return False
    mine = len(g.cities_of(f))
    theirs = len(g.cities_of(proposer))
    p = 0.15
    if mine < 0.8 * theirs:
        p = 0.7
    elif fac.doctrine == "aggressive" and mine > 1.2 * theirs:
        p = 0.03
    if g.doomsday <= 4:
        p += 0.3
    return g.rng.random() < p


def run_ai_turns(g: Game) -> None:
    """Play AI factions until it is a human's turn or the game is over."""
    while not g.over and not g.faction.human:
        AI(g, g.current).play()
        g.end_turn()
