"""The war bulletin: every action is recorded, and each faction is shown
what the others did since its own last turn, through its fog of war."""

import pytest

from theempire import commands
from theempire.game import Game
from theempire.world import load_world


@pytest.fixture(scope="module")
def world():
    return load_world()


def _game(world, humans=("west",)):
    return Game("ww3", humans=humans, seed=7, world=world)


def test_bulletin_after_an_ai_round(world):
    g = _game(world)
    commands.advance(g)
    commands.newsreel(g, 0)               # empty the first one
    commands.apply(g, 0, {"op": "end_turn"})
    reel = commands.newsreel(g, 0)
    ops = {a["op"] for a in reel}
    assert "move" in ops or "attack" in ops or "capture" in ops
    assert all(a["actor"] != 0 for a in reel)          # never our own actions
    # shown once: the next call starts from where this one ended
    assert commands.newsreel(g, 0) == []
    for move in (a for a in reel if a["op"] == "move"):
        assert {"cell", "unit", "glyph", "owner"} <= set(move)


def test_bulletin_respects_the_fog_of_war(world):
    g = _game(world)
    commands.apply(g, 0, {"op": "end_turn"})
    vis = g.visible(0)
    for a in commands.newsreel(g, 0):
        if a["op"] == "move":
            assert a["cell"] in vis
        if a["op"] == "attack":
            assert a["cell"] in vis or a["defender"] == 0


def test_attacks_remember_origin_and_outcome(world):
    g = _game(world)
    for _ in range(6):
        commands.apply(g, 0, {"op": "end_turn"})
    attacks = [a for a in g.reel if a["op"] == "attack"]
    assert attacks
    for a in attacks:
        assert a["frm"] in g.world.neighbors[a["cell"]]
        assert a["result"] in ("won", "lost", "captured")


def test_hot_seat_players_see_each_other(world):
    g = _game(world, humans=("west", "east"))
    commands.advance(g)
    commands.newsreel(g, 1)
    u = next(x for x in g.units_of(0) if x.kind == "A")
    step = next(n for n in g.world.neighbors[u.cell] if g.classify(u, n) == "move")
    g.move(u, step)
    reel = g.take_reel(1)
    assert any(a["op"] == "move" and a["unit"] == u.id for a in reel)


def test_bulletin_is_not_saved(world, tmp_path):
    g = _game(world)
    commands.apply(g, 0, {"op": "end_turn"})
    assert g.reel
    path = tmp_path / "save.json"
    g.save_file(path)
    assert Game.load_file(path).reel == []
