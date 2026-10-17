"""Production directives, the local turn timer and Empire-style mouse orders."""

import curses

import pytest

from theempire import commands
from theempire.audio import EscapeAudio
from theempire.game import DIRECTIVES, Game
from theempire.net import LocalSession
from theempire.ui import UI
from theempire.units import UNIT_TYPES, WARHEAD
from theempire.world import load_world


@pytest.fixture(scope="module")
def world():
    return load_world()


def game(world):
    g = Game("ww3", humans=("west",), seed=3, world=world)
    commands.advance(g)
    return g


def test_air_directive_converts_every_city(world):
    g = game(world)
    assert commands.apply(g, 0, {"op": "directive", "name": "air"}) != "illegal"
    for c in g.cities_of(0):
        assert UNIT_TYPES[c.production].domain == "air"


def test_sea_directive_keeps_inland_cities_on_land(world):
    g = game(world)
    commands.apply(g, 0, {"op": "directive", "name": "sea"})
    for c in g.cities_of(0):
        domain = UNIT_TYPES[c.production].domain
        assert domain == ("sea" if g.is_port(c.cell) else "land")


def test_hand_picked_cities_are_left_alone_until_released(world):
    g = game(world)
    city = g.cities_of(0)[0]
    assert commands.apply(g, 0, {"op": "produce", "city": city.id, "key": "I"}) == "ok"
    assert city.manual
    commands.apply(g, 0, {"op": "directive", "name": "air"})
    assert city.production == "I"
    commands.apply(g, 0, {"op": "release", "city": city.id})
    assert UNIT_TYPES[city.production].domain == "air"
    # "all" overrides the hand-picked ones too
    commands.apply(g, 0, {"op": "produce", "city": city.id, "key": "I"})
    commands.apply(g, 0, {"op": "directive", "name": "defense", "all": True})
    assert all(c.production == "I" for c in g.cities_of(0))


def test_nuclear_directive_and_new_cities_follow(world):
    g = game(world)
    commands.apply(g, 0, {"op": "directive", "name": "nuclear"})
    big = [c for c in g.cities_of(0) if c.capital or c.size == 3]
    assert big and all(c.production == WARHEAD for c in big if g.can_build(c, WARHEAD))
    neutral = next(c for c in g.cities if c.owner is None)
    neutral.owner = 0                    # taken during the round...
    g.prepared = None
    commands.prepare_human_turn(g)       # ...follows the directive next turn
    assert neutral.production == g.directive_choice(neutral, "nuclear")


def test_every_directive_is_valid(world):
    g = game(world)
    for name in DIRECTIVES:
        commands.apply(g, 0, {"op": "directive", "name": name})
        assert all(g.can_build(c, c.production) for c in g.cities_of(0))
    assert commands.apply(g, 0, {"op": "directive", "name": "bogus"}) == "illegal"


def test_local_turn_clock(world, tmp_path):
    s = LocalSession(game(world), tmp_path / "s.json", turn_time=60)
    assert s.seconds_left() is None      # not started yet
    s.start_clock()
    assert 59 <= s.seconds_left() <= 60
    s.clock_started -= 61
    assert s.seconds_left() == 0
    assert LocalSession(s.game, tmp_path / "s.json").seconds_left() is None


class FakeScr:
    def getmaxyx(self):
        return 50, 200


def ui_for(world, tmp_path):
    ui = object.__new__(UI)
    ui.scr = FakeScr()
    ui.w = world
    ui.session = LocalSession(game(world), tmp_path / "s.json")
    ui.audio = EscapeAudio(write=lambda data: None)
    ui.viewer = 0
    ui.view_x, ui.view_y = 0, 0
    ui.cursor = 0
    ui.mode = "normal"
    ui._pan = ui._pan_view = None
    ui.active_id = None
    ui.skipped = set()
    ui.status = ""
    ui.turn_key = (ui.session.game.turn, ui.session.game.current)
    ui.over_shown = False
    ui.last_seq = 0
    ui.reveal, ui.phantom = set(), {}
    return ui


def free_neighbour(g, u):
    return next(n for n in g.world.neighbors[u.cell] if g.classify(u, n) == "move")


def test_click_next_to_the_unit_moves_it(world, tmp_path):
    ui = ui_for(world, tmp_path)
    g = ui.g
    u = next(x for x in g.units_of(0) if x.kind == "A")
    u.order = None
    ui.active = u
    target = free_neighbour(g, u)
    ui.click(target)
    assert u.cell == target


def test_far_click_shows_route_then_second_click_sends(world, tmp_path):
    ui = ui_for(world, tmp_path)
    g = ui.g
    u = next(x for x in g.units_of(0) if x.kind == "A")
    u.order = None
    ui.active = u
    # a land cell a few steps away
    far = next(c for c in g.world.ring(u.cell, 4)
               if g.world.dist(c, u.cell) == 4 and g.path(u, c))
    ui.click(far)
    assert ui.mode == "goto" and ui.cursor == far
    start = u.cell
    ui.click(far)
    assert ui.mode == "normal"
    assert u.cell != start and (u.order == "goto" or u.cell == far)


def test_click_on_own_unit_selects_it(world, tmp_path):
    ui = ui_for(world, tmp_path)
    g = ui.g
    city = next(c for c in g.cities_of(0) if any(u.owner == 0 for u in g.units_at(c.cell)))
    ui.click(city.cell)
    assert ui.active is not None and ui.active.cell == city.cell


def test_wheel_scrolls(world, tmp_path, monkeypatch):
    ui = ui_for(world, tmp_path)
    ui.view_y = 20
    monkeypatch.setattr(curses, "getmouse", lambda: ("", 10, 10, 0, curses.BUTTON5_PRESSED))
    ui.mouse()
    assert ui.view_y == 23
