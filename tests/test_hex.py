"""The optional hex grid: 6 neighbours, hex distances, the odd rows drawn
half a cell east."""

import random
import sys
from pathlib import Path

import pytest

from theempire.game import Game
from theempire.world import load_world

sys.path.insert(0, str(Path(__file__).parent))
from test_map import _cell, _sea_path, _ui_with_curses  # noqa: E402


@pytest.fixture(scope="module")
def hexes():
    return load_world(True)


def test_six_neighbours_and_hex_distances(hexes):
    assert hexes.hexgrid and not load_world().hexgrid
    rng = random.Random(1)
    for _ in range(100):
        a = rng.randrange(hexes.width, hexes.size - hexes.width)
        assert len(hexes.neighbors[a]) == 6
        for n in hexes.neighbors[a]:
            assert a in hexes.neighbors[n]
        steps = hexes.bfs([a], lambda i: True, limit=5)
        for c, d in steps.items():
            assert hexes.dist(a, c) == d
        assert sorted(hexes.ring(a, 2)) == sorted(c for c, d in steps.items() if d <= 2)


def test_slanted_steps(hexes):
    even, odd = hexes.idx(10, 10), hexes.idx(10, 11)
    assert hexes.step_dir(even, 1, -1) == hexes.idx(10, 9)      # north-east of an even row
    assert hexes.step_dir(even, -1, -1) == hexes.idx(9, 9)
    assert hexes.step_dir(odd, 1, 1) == hexes.idx(11, 12)       # odd rows sit half a cell east
    assert hexes.step_dir(odd, -1, 1) == hexes.idx(10, 12)
    assert hexes.step_dir(even, 0, -1) is None                  # no straight north
    for i in (even, odd):
        steps = {hexes.step_dir(i, dx, dy) for dx, dy in ((1, 0), (-1, 0), (1, -1), (-1, -1), (1, 1), (-1, 1))}
        assert steps == set(hexes.neighbors[i])


def test_straits_stay_open(hexes):
    steps = _sea_path(hexes, _cell(hexes, -6, 37), _cell(hexes, 31, 35))   # Gibraltar to the Levant
    assert steps is not None and steps > 0
    for site in hexes.sites:
        assert hexes.land[site.cell]


def test_game_option_survives_saving():
    g = Game("europe", humans=("nato",), seed=1, hexgrid=True)
    assert g.options["hex"] and g.world.hexgrid
    again = Game.from_dict(g.to_dict(), load_world())       # the square world is swapped out
    assert again.world.hexgrid
    assert not Game("europe", seed=1, world=load_world()).options["hex"]


def test_path_moves_by_hexes(hexes):
    g = Game("ww3", humans=("west",), seed=1, hexgrid=True)
    tank = next(u for u in g.units_of(0) if u.kind == "A")
    far = next(c for c in hexes.ring(tank.cell, 4) if hexes.dist(tank.cell, c) == 4 and g.path(tank, c))
    route = g.path(tank, far)
    assert len(route) == 4
    prev = tank.cell
    for c in route:
        assert c in hexes.neighbors[prev]
        prev = c


def test_odd_rows_are_drawn_half_a_cell_east(monkeypatch):
    ui = _ui_with_curses(monkeypatch)
    ui.w = load_world(True)
    ui.session.game = Game("ww3", humans=("west",), seed=1, world=ui.w)
    assert ui.ZOOMS == (2, 4)
    ui.zoom = 0                                       # 2×2 characters a cell
    ui.view_y = 10                                    # an even row on top
    assert ui._cell_at(0, 1) == ui.w.idx(100, 10)
    assert ui._cell_at(0, 3) == ui.w.idx(99, 11)      # the end of the cell before
    assert ui._cell_at(1, 3) == ui.w.idx(100, 11)
    assert ui._cell_at(2, 3) == ui.w.idx(100, 11)
    assert ui._cell_at(3, 3) == ui.w.idx(101, 11)


def test_the_honeycomb_is_drawn():
    from theempire.ui import hex_border
    for k in (2, 4):
        border = hex_border(k)
        assert len(border) == k and all(len(row) == k for row in border)
        assert all(row[0] for row in border)             # the west wall, top to bottom
        assert any(border[0][1:])                         # the pointed roof
