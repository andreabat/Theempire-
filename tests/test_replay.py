"""The AI-turn newsreel: actions are recorded while the AI plays, then the
interface replays them as an animated summary with sounds."""

import pytest

from theempire import commands
from theempire.game import Game
from theempire.scenarios import SCENARIOS
from theempire.ui import UI
from theempire.world import load_world


@pytest.fixture(scope="module")
def world():
    return load_world()


def _game(world):
    return Game("ww3", humans=(SCENARIOS["ww3"].factions[0].key,), seed=7, world=world)


def test_ai_turn_records_actions(world):
    g = _game(world)
    assert g.replay == []
    commands.advance(g)  # west is already to move: no AI, no recording
    assert g.replay == []
    commands.apply(g, g.current, {"op": "end_turn"})  # a full AI round
    ops = {a["op"] for a in g.replay}
    assert "move" in ops
    assert g.recording is False
    # every move carries what the newsreel needs to draw its phantom
    for move in (a for a in g.replay if a["op"] == "move"):
        assert {"cell", "unit", "glyph", "owner"} <= set(move)


def test_human_moves_are_not_recorded(world):
    g = _game(world)
    g.recording = False
    u = g.units_of(g.current)[0]
    for n in g.world.neighbors[u.cell]:
        if g.classify(u, n) == "move":
            g.move(u, n)
            break
    assert g.replay == []


def test_replay_is_not_saved(world, tmp_path):
    g = _game(world)
    commands.apply(g, g.current, {"op": "end_turn"})
    assert g.replay
    path = tmp_path / "save.json"
    g.save_file(path)
    loaded = Game.load_file(path)
    assert loaded.replay == []


def test_replay_sound_perspective(world):
    ui = object.__new__(UI)  # _replay_sound only reads .viewer
    ui.viewer = 2
    nuke = {"op": "nuke", "cell": 0}
    chem = {"op": "chem", "cell": 0}
    fall = {"op": "fall", "cell": 0}
    assert ui._replay_sound(nuke) == "nuke"
    assert ui._replay_sound(chem) == "gas"
    assert ui._replay_sound(fall) == "fall"
    assert ui._replay_sound({"op": "capture", "new": 2, "old": 1}) is None
    assert ui._replay_sound({"op": "capture", "new": 1, "old": 2}) == "loss"
    assert ui._replay_sound({"op": "capture", "new": 1, "old": 3}) is None
    assert ui._replay_sound({"op": "attack"}) == "battle"
    assert ui._replay_sound({"op": "move"}) is None