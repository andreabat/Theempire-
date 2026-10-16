import random

import pytest

from theempire.ai import AI
from theempire.game import Game, win_probability
from theempire.scenarios import SCENARIOS
from theempire.world import load_world


class AlwaysWin(random.Random):
    """An RNG under which the attacker wins every combat round."""

    def random(self):
        return 0.0


@pytest.fixture(scope="module")
def world():
    return load_world()


def empty_game(world, scenario="ww3"):
    g = Game(scenario, humans=(SCENARIOS[scenario].factions[0].key,), seed=7, world=world)
    for u in list(g.units.values()):
        g.kill(u)
    return g


def inland_cell(g, near_city=False):
    """A land cell whose neighbours are all land and free of cities."""
    w = g.world
    for i in range(w.size):
        if not w.land[i] or g.city(i) or i in g.at:
            continue
        ns = w.neighbors[i]
        if len(ns) == 8 and all(w.land[n] and g.city(n) is None and n not in g.at for n in ns):
            return i
    raise AssertionError("no inland cell")


def coast_pair(g):
    """(sea cell, adjacent free land cell without city)."""
    w = g.world
    for i in range(w.size):
        if w.land[i] or i in g.at:
            continue
        for n in w.neighbors[i]:
            if w.land[n] and g.city(n) is None and n not in g.at:
                return i, n
    raise AssertionError


def test_world_shape(world):
    assert world.width == 360 and world.height == 72
    assert len(world.land) == world.size
    assert len(world.sites) >= 300
    # East-west wrap: the cell left of x=0 is x=width-1.
    assert world.idx(-1, 10) == world.idx(world.width - 1, 10)
    assert world.dist(world.idx(0, 10), world.idx(world.width - 1, 10)) == 1
    names = {s.name for s in world.sites}
    for city in ("Rome", "Moscow", "Beijing", "Washington, D.C.", "London"):
        assert city in names


def test_win_probability():
    assert win_probability(1, 1, 1, 1) == pytest.approx(0.5)
    assert win_probability(4, 3, 1, 1) > 0.9
    assert win_probability(1, 1, 4, 3) < 0.1


def test_move_and_terrain(world):
    g = empty_game(world)
    cell = inland_cell(g)
    u = g.create_unit("A", 0, cell)
    target = world.neighbors[cell][0]
    assert g.move(u, target) == "moved"
    assert u.cell == target and u.moves == 1
    sea, land = coast_pair(g)
    tank = g.create_unit("I", 0, land)
    assert g.classify(tank, sea) is None
    ship = g.create_unit("D", 0, sea)
    assert g.classify(ship, land) is None


def test_one_unit_per_cell_and_attack(world):
    g = empty_game(world)
    g.rng = AlwaysWin()
    cell = inland_cell(g)
    a = g.create_unit("A", 0, cell)
    n = world.neighbors[cell][0]
    friend = g.create_unit("I", 0, n)
    assert g.classify(a, n) is None
    g.kill(friend)
    enemy = g.create_unit("I", 1, n)
    assert g.classify(a, n) == "attack"
    assert g.move(a, n) == "won"
    assert enemy.id not in g.units and a.cell == cell


def test_capture_neutral_city(world):
    g = empty_game(world)
    g.rng = AlwaysWin()
    city = next(c for c in g.cities if c.owner is None
                and any(world.land[n] and g.city(n) is None for n in world.neighbors[c.cell]))
    start = next(n for n in world.neighbors[city.cell] if world.land[n] and g.city(n) is None)
    a = g.create_unit("A", 0, start)
    assert g.move(a, city.cell) == "captured"
    assert city.owner == 0 and a.cell == city.cell


def test_transport_board_and_land(world):
    g = empty_game(world)
    sea, land = coast_pair(g)
    t = g.create_unit("T", 0, sea)
    inf = g.create_unit("I", 0, land)
    assert g.move(inf, sea) == "moved"
    assert inf.carrier == t.id and inf.id in t.cargo
    # The cargo travels with the ship.
    nxt = next(n for n in world.neighbors[sea] if not world.land[n] and n not in g.at)
    assert g.move(t, nxt) == "moved"
    assert inf.cell == nxt
    g.begin_turn()
    inf.order = None
    shore = next((n for n in world.neighbors[nxt] if world.land[n] and n not in g.at and g.city(n) is None), None)
    if shore is not None:
        assert g.move(inf, shore) == "moved"
        assert inf.carrier is None and inf.cell == shore
    # Sinking a loaded transport drowns its cargo.
    inf2 = g.create_unit("I", 0, land)
    g.move(t, sea)
    g._embark(inf2, t)
    g.kill(t)
    assert inf2.id not in g.units


def test_aircraft_run_out_of_fuel(world):
    g = empty_game(world)
    sea, _ = coast_pair(g)
    f = g.create_unit("F", 0, sea)
    f.fuel = 1
    nxt = next(n for n in world.neighbors[sea] if n not in g.at and g.city(n) is None)
    assert g.move(f, nxt) == "crashed"
    assert f.id not in g.units


def test_nuclear_strike_and_armageddon(world):
    g = empty_game(world)
    g.factions[1].abm = 0.0
    cell = inland_cell(g)
    victims = [g.create_unit("I", 1, c) for c in world.ring(cell, 1)]
    before = g.doomsday
    assert g.nuclear_strike(0, cell) == "hit"
    assert all(v.id not in g.units for v in victims)
    assert g.doomsday == before - 2
    assert cell in g.fallout
    assert 0 in g.factions[1].nuked_by
    g.doomsday = 2
    g.factions[0].warheads = 5
    g.nuclear_strike(0, cell)
    assert g.over == (None, "armageddon")


def test_chemical_needs_range(world):
    g = empty_game(world)
    cell = inland_cell(g)
    g.factions[0].chemicals = 1
    far = world.idx(world.xy(cell)[0] + 40, world.xy(cell)[1])
    assert not g.can_chemical(0, far) or any(
        c.owner == 0 and world.dist(c.cell, far) <= 4 for c in g.cities)
    g.create_unit("I", 0, cell)
    assert g.can_chemical(0, world.neighbors[cell][0])


def test_supply_limit_stops_production(world):
    g = empty_game(world)
    city = g.cities_of(0)[0]
    city.production = "I"
    city.progress = 100
    while len(g.units_of(0)) < g.supply_limit(0):
        g.create_unit("I", 0, city.cell)
    n = len(g.units_of(0))
    g.current = 0
    g.begin_turn()
    assert len(g.units_of(0)) == n
    assert city.progress == 6  # waits, fully paid, for supply to free up


def test_save_load_roundtrip(world, tmp_path):
    g = Game("ww3", humans=("west",), seed=3, world=world)
    AI(g, 0).play()
    g.end_turn()
    path = tmp_path / "save.json"
    g.save_file(path)
    h = Game.load_file(path)
    assert h.to_dict() == g.to_dict()
    # Both continue identically.
    AI(g, g.current).play()
    AI(h, h.current).play()
    assert h.to_dict()["units"] == g.to_dict()["units"]


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_ai_plays_every_scenario(world, scenario):
    g = Game(scenario, seed=11, world=world)
    for _ in range(4 * len(g.factions)):
        AI(g, g.current).play()
        g.end_turn()
    assert g.turn >= 4
    assert all(u.cell in g.at or u.carrier is not None for u in g.units.values())
    for cell, ids in g.at.items():
        top = [g.units[i] for i in ids]
        if g.city(cell) is None:
            assert len(top) == 1, "one unit per cell outside cities"
