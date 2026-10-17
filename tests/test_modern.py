"""Today's weapons: drones, hypersonic missiles, spy satellites and ASATs."""

import random

import pytest

from theempire import commands
from theempire.ai import AI
from theempire.game import Game
from theempire.units import ASAT, MODERN, SATELLITE, UNIT_TYPES
from theempire.world import load_world


class AlwaysWin(random.Random):
    def random(self):
        return 0.0


@pytest.fixture(scope="module")
def world():
    return load_world()


def big_city(g, f):
    return next(c for c in g.cities_of(f) if c.size >= 3)


def test_not_in_the_cold_war(world):
    cold = Game("coldwar", seed=1, world=world)
    for key in MODERN:
        assert not any(cold.can_build(c, key) for c in cold.cities)
    tutorial = Game("tutorial", seed=1, world=world)
    assert not any(tutorial.can_build(c, "U") for c in tutorial.cities)
    ww3 = Game("ww3", seed=1, world=world)
    city = big_city(ww3, 0)
    assert all(ww3.can_build(city, key) for key in MODERN)
    small = next(c for c in ww3.cities_of(0) if c.size == 1 and not c.capital)
    assert not ww3.can_build(small, SATELLITE) and not ww3.can_build(small, ASAT)
    assert ww3.can_build(small, "U")


def test_a_missile_is_spent_in_its_strike(world):
    g = Game("ww3", seed=1, world=world)
    g.rng = AlwaysWin()
    sea = next(i for i in range(world.size) if not world.land[i] and i not in g.at
               and all(not world.land[n] and n not in g.at for n in world.neighbors[i]))
    ship = g.create_unit("R", 1, sea)
    launch = next(n for n in world.neighbors[sea] if n not in g.at)
    missile = g.create_unit("H", 0, launch)
    assert g.move(missile, sea) == "won"
    assert ship.id not in g.units and missile.id not in g.units


def test_drones_see_far(world):
    g = Game("ww3", seed=1, world=world)
    drone = UNIT_TYPES["U"]
    assert drone.vision > UNIT_TYPES["F"].vision and drone.cost < UNIT_TYPES["F"].cost


def test_satellite_watches_a_band_and_moves(world):
    g = Game("ww3", seed=1, world=world)
    f = 0
    city = big_city(g, f)
    far = next(u for u in g.units.values() if u.owner == 2 and u.carrier is None)
    assert not g.sees(f, far)
    g.factions[f].satellites.append(far.cell % world.width)    # right above it
    g._dirty()
    assert g.sees(f, far)
    stealthy = g.create_unit("S", 2, next(i for i in range(far.cell % world.width, world.size, world.width)
                                          if not world.land[i] and i not in g.at))
    assert not g.sees(f, stealthy)                             # submarines stay hidden
    before = list(g.factions[f].satellites)
    g._orbit()
    assert g.factions[f].satellites != before
    # building one launches it above the city
    city.production, city.progress = SATELLITE, 1000.0
    g.current = f
    g.begin_turn()
    assert city.cell % world.width in g.factions[f].satellites


def test_asat_shoots_satellites_down(world):
    g = Game("ww3", seed=1, world=world)
    g.rng = AlwaysWin()
    assert g.asat_strike(0, 1) == "noasat"
    g.factions[0].asats = 2
    assert g.asat_strike(0, 1) == "nosat"
    g.factions[1].satellites = [10, 200]
    assert commands.apply(g, 0, {"op": "asat", "target": 1}) == "ok"
    assert len(g.factions[1].satellites) == 1 and g.factions[0].asats == 1


def test_satellite_orbits_are_secret_online(world):
    g = Game("ww3", seed=1, world=world)
    g.factions[1].satellites = [10, 200]
    g.factions[1].asats = 3
    view = commands.view_for(g, 0)
    assert view["factions"][1]["satellites"] == [-1, -1] and view["factions"][1]["asats"] == 0


def test_ai_fires_asats_at_spies(world):
    g = Game("ww3", seed=1, world=world)
    g.rng = AlwaysWin()
    g.factions[1].satellites = [50]
    g.factions[2].asats = 1
    AI(g, 2).space()
    assert g.factions[1].satellites == [] and g.factions[2].asats == 0
