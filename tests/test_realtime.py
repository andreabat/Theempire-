"""Real time: no turns, a pulse every few seconds."""

import time

import pytest

from theempire import commands
from theempire.game import Game
from theempire.net import GameServer, LocalSession
from theempire.world import load_world


@pytest.fixture(scope="module")
def world():
    return load_world()


def test_a_pulse_is_a_whole_round(world):
    g = Game("ww3", humans=("west",), seed=1, world=world, realtime=10)
    assert g.realtime == 10 and g.options["realtime"] == 10
    tank = next(u for u in g.units_of(0) if u.kind == "A")
    tank.moves = 0
    turn, current = g.turn, g.current
    commands.tick(g)
    assert g.turn == turn + 1 and g.current == current
    assert tank.moves == tank.type.move                 # the pulse gave the moves back
    assert Game.from_dict(g.to_dict(), world).realtime == 10


def test_players_act_whenever_they_like(world):
    g = Game("ww3", humans=("west", "east"), seed=1, world=world, realtime=10)
    g.current = 2                                       # an AI faction is "current": nobody cares
    u = next(u for u in g.units_of(1) if u.kind == "A")
    step = next(n for n in world.neighbors[u.cell] if g.classify(u, n) == "move")
    assert commands.apply(g, 1, {"op": "move", "unit": u.id, "cell": step}) == "moved"
    assert commands.apply(g, 2, {"op": "end_turn"}) == "illegal"       # not a player
    assert commands.apply(g, 0, {"op": "end_turn"}) == "realtime"      # two players: no skipping
    alone = Game("ww3", humans=("west",), seed=1, world=world, realtime=10)
    turn = alone.turn
    assert commands.apply(alone, 0, {"op": "end_turn"}) == "ok" and alone.turn == turn + 1


def test_local_pulses_come_by_themselves(world, tmp_path):
    g = Game("ww3", humans=("west",), seed=1, world=world, realtime=10)
    session = LocalSession(g, tmp_path / "save.json")
    session.start()
    assert not session.poll() and 9 <= session.seconds_left() <= 10
    session.last_pulse = time.time() - 11
    turn = g.turn
    assert session.poll() and g.turn == turn + 1
    assert session.seconds_left() >= 9


def test_turn_based_games_are_unchanged(world):
    g = Game("ww3", humans=("west",), seed=1, world=world)
    assert g.realtime == 0
    g.current = 1
    assert commands.apply(g, 0, {"op": "end_turn"}) == "notyourturn"


def test_server_pulses_for_everybody(world):
    g = Game("coldwar", humans=("nato", "pact"), seed=1, world=world, realtime=5)
    srv = GameServer(g, "127.0.0.1", 0, log=lambda line: None)
    srv.started = True
    turn = g.turn
    srv._pulse()
    assert g.turn == turn                                # not yet
    srv.last_pulse = time.time() - 6
    srv._pulse()
    assert g.turn == turn + 1
    assert 0 < srv._deadline() <= 5
