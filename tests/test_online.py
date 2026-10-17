import threading
import time

import pytest

from theempire import commands
from theempire.game import Game
from theempire.net import GameServer, LocalSession, RemoteSession
from theempire.world import load_world


@pytest.fixture()
def server(tmp_path):
    game = Game("coldwar", humans=("nato", "pact"), seed=5, world=load_world())
    srv = GameServer(game, "127.0.0.1", 0, password="segreto",
                     save_path=tmp_path / "server.json", log=lambda line: None)
    srv.listen()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.stop()


def join(server, tmp_path, who, faction=None, password="segreto"):
    return RemoteSession("127.0.0.1", server.port, who, faction, password,
                         tokens_file=tmp_path / f"{who}.json")


def wait_for(session, check, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        session.poll()
        if check(session.game):
            return True
        time.sleep(0.05)
    return False


def test_lobby_turns_and_fog(server, tmp_path):
    a = join(server, tmp_path, "anna", "nato")
    assert a.faction == 0 and not a.started
    assert a.do(0, {"op": "end_turn"}) == "waiting"
    b = join(server, tmp_path, "bruno")
    assert b.faction == 1
    assert b.do(1, {"op": "end_turn"}) == "notyourturn"
    # Each player only receives enemy units its own forces can see.
    g = server.game
    hidden = [u for u in g.units.values() if u.owner == 1 and not g.sees(0, u)]
    assert hidden
    assert wait_for(a, lambda g: True)
    assert all(a.game.units.get(u.id) is None for u in hidden)
    assert a.do(0, {"op": "chat", "text": "ciao\x1b[2J"}) == "ok"
    assert not any("\x1b" in e.text for e in g.events)
    assert a.do(0, {"op": "end_turn"}) == "ok"
    assert wait_for(b, lambda g: g.current == 1)
    assert any("ciao" in e.text for e in b.game.events)
    # A forged command for someone else's unit is refused.
    enemy = next(u for u in g.units.values() if u.owner == 0)
    assert b.do(1, {"op": "disband", "unit": enemy.id}) == "illegal"
    assert enemy.id in g.units
    a.close()
    b.close()


def test_password_and_rejoin(server, tmp_path):
    with pytest.raises(ConnectionError):
        join(server, tmp_path, "intruso", password="sbagliata")
    a = join(server, tmp_path, "anna", "nato")
    a.close()
    # Same player, same stored token: gets the seat back.
    again = join(server, tmp_path, "anna")
    assert again.faction == 0
    b = join(server, tmp_path, "bruno")
    with pytest.raises(ConnectionError):
        join(server, tmp_path, "carla")  # the game is full
    again.close()
    b.close()


def test_local_session_matches_commands(tmp_path):
    g = Game("ww3", humans=("west",), seed=2, world=load_world())
    s = LocalSession(g, tmp_path / "save.json")
    s.start()
    assert s.do(0, {"op": "save"}) == "saved"
    assert (tmp_path / "save.json").exists()
    assert s.do(0, {"op": "move", "unit": 10 ** 9, "cell": 0}) == "illegal"


def test_view_for_hides_rng_and_foreign_events():
    g = Game("ww3", humans=("west",), seed=2, world=load_world())
    g.log("segreto", [1])
    view = commands.view_for(g, 0)
    assert all("segreto" not in e["text"] for e in view["events"])
    assert view["rng"] != g.to_dict()["rng"]


def test_truce_blocks_attacks():
    w = load_world()
    g = Game("coldwar", humans=("nato", "pact"), seed=1, world=w)
    for u in list(g.units.values()):
        g.kill(u)
    cell = next(i for i in range(w.size) if w.land[i] and g.city(i) is None
                and all(w.land[n] and g.city(n) is None for n in w.neighbors[i]))
    a = g.create_unit("A", 0, cell)
    n = w.neighbors[cell][0]
    g.create_unit("I", 1, n)
    assert g.classify(a, n) == "attack"
    assert g.propose_truce(0, 1) == "pending"
    assert g.proposals_to(1) == [0]
    assert g.answer_truce(1, 0, True) == "accepted"
    assert g.truce_left(0, 1) > 0
    assert g.classify(a, n) is None
    assert g.nuclear_strike(0, n) == "truce"
    g.turn += 20
    g._new_round()
    assert g.truce_left(0, 1) == 0 and g.classify(a, n) == "attack"


def test_online_players_get_their_bulletin(tmp_path):
    game = Game("ww3", humans=("west", "east"), seed=5, world=load_world())
    srv = GameServer(game, "127.0.0.1", 0, log=lambda line: None)
    srv.listen()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        a = RemoteSession("127.0.0.1", srv.port, "anna", "west", tokens_file=tmp_path / "a.json")
        b = RemoteSession("127.0.0.1", srv.port, "bruno", "east", tokens_file=tmp_path / "b.json")
        assert wait_for(a, lambda g: True)
        a.take_reel(0)
        assert a.do(0, {"op": "end_turn"}) == "ok"
        assert wait_for(b, lambda g: g.current == 1)
        assert b.do(1, {"op": "end_turn"}) == "ok"      # then the AI (China) plays
        assert wait_for(a, lambda g: g.current == 0 and g.turn == 2)
        reel = a.take_reel(0)
        assert reel, "west receives what the others did"
        assert all(x["actor"] != 0 for x in reel)
        assert a.take_reel(0) == []                      # only once
        a.close()
        b.close()
    finally:
        srv.stop()
