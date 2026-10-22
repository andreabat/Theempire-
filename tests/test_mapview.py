"""The graphical web map: its data, the server's watchers and the gateway."""

import base64
import json
import os
import socket
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from theempire import commands, mapview
from theempire.game import Game
from theempire.net import MAX_SERVER_MESSAGE, PROTOCOL, GameServer, RemoteSession, recv_msg, send_msg
from theempire.web import WebGateway
from theempire.world import load_world

sys.path.insert(0, str(Path(__file__).parent))
from test_web import WSClient  # noqa: E402


def unbits(b64: str, n: int) -> list[int]:
    raw = base64.b64decode(b64)
    return [(raw[i >> 3] >> (7 - (i & 7))) & 1 for i in range(n)]


def test_land_mask_is_a_png():
    png = mapview.land_png()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and b"IHDR" in png and b"IEND" in png
    w = mapview.world()
    assert w["hd"] == [8, 16] and not w["hex"] and mapview.world(True)["hex"]
    land = unbits(w["land"], w["width"] * w["height"])
    assert land == list(load_world().land)


def test_view_shows_only_what_the_faction_sees():
    g = Game("ww3", humans=("west",), seed=1)
    d = mapview.view(commands.view_for(g, 0), 0, "en")
    owners = {u[2] for u in d["units"]}
    assert 0 in owners
    vis = unbits(d["visible"], g.world.size)
    for u in d["units"]:
        assert u[2] == 0 or vis[u[3]]
    assert len(d["territory"]) == g.world.size
    assert d["factions"][0]["warheads"] is not None and d["factions"][1]["warheads"] is None
    assert d["factions"][0]["name"] == "Atlantic Alliance"         # in the reader's language
    assert {c[5] for c in d["cities"]} >= {-1, 0, 1, 2}


def test_theatre_and_hexes():
    g = Game("europe", humans=("nato",), seed=1, hexgrid=True)
    d = mapview.view(commands.view_for(g, 0), 0)
    assert d["hex"] and d["theatre"] is not None
    assert sum(unbits(d["theatre"], g.world.size)) == sum(g.theatre)


@pytest.fixture()
def server(tmp_path, monkeypatch):
    import theempire.web as web
    monkeypatch.setattr(web, "WEB_HOMES", tmp_path / "homes")
    srv = GameServer(Game("europe", humans=("nato",), seed=1), "127.0.0.1", 0, password="pw",
                     log=lambda line: None)
    srv.listen()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, tmp_path
    srv.stop()


def watch(port: int, token: str) -> tuple[socket.socket, dict]:
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    send_msg(sock, {"type": "hello", "version": PROTOCOL, "watch": True, "token": token})
    return sock, recv_msg(sock, MAX_SERVER_MESSAGE)


def test_watchers_need_a_seat_and_only_read(server):
    srv, tmp = server
    sock, reply = watch(srv.port, "nope")
    assert reply["type"] == "error"
    sock.close()
    player = RemoteSession("127.0.0.1", srv.port, "Anna", password="pw", tokens_file=tmp / "t.json")
    token = srv.slots[0].token
    sock, reply = watch(srv.port, token)                      # no password: the token is enough
    assert reply["type"] == "welcome" and reply["watch"] and reply["faction"] == 0
    assert recv_msg(sock, MAX_SERVER_MESSAGE)["type"] == "state"
    assert srv.slots[0].conn is not None                      # the player keeps the seat
    send_msg(sock, {"type": "cmd", "id": 1, "cmd": {"op": "end_turn"}})
    turn = srv.game.turn
    assert player.do(0, {"op": "end_turn"}) == "ok"
    msg = recv_msg(sock, MAX_SERVER_MESSAGE)                  # the watcher follows the game
    assert msg["type"] == "state"
    assert srv.game.turn >= turn
    sock.close()


def test_gateway_serves_the_map(server):
    srv, tmp = server
    gw = WebGateway(("127.0.0.1", srv.port), "127.0.0.1", 0, srv.web_info, log=lambda line: None)
    gw.listen()
    threading.Thread(target=gw.serve_forever, daemon=True).start()
    try:
        get = lambda path: urllib.request.urlopen(f"http://127.0.0.1:{gw.port}{path}", timeout=10)
        assert b"<canvas" in get("/map").read()
        assert get("/map/land.png").read()[:4] == b"\x89PNG"
        assert json.loads(get("/map/world.json?hex=1").read())["hex"]
        browser = os.urandom(16).hex()
        ws = WSClient(gw.port, f"/map/ws?id={browser}&lang=it")
        assert b"noseat" in ws.read_until(rb"noseat")
        # the browser's terminal client takes a seat: the map follows it
        home = tmp / "homes" / browser / ".theempire"
        RemoteSession("127.0.0.1", srv.port, "Anna", password="pw", tokens_file=home / "online.json")
        out = ws.read_until(rb'"t":"state"', timeout=20)
        assert b'"territory"' in out and b'"viewer":0' in out
        ws.close()
    finally:
        gw.stop()
