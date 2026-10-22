"""The web TUI gateway: page, assets, sounds and a real terminal session."""

import base64
import json
import os
import re
import socket
import struct
import threading
import time
import urllib.error
import urllib.request

import pytest

from theempire.game import Game
from theempire.net import GameServer
from theempire.web import WebGateway, WebSocket
from theempire.world import load_world


class WSClient:
    """A tiny WebSocket client, enough to drive the gateway."""

    def __init__(self, port: int, path: str):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {path} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                        "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.s.recv(1)
        self.status = head.split(b"\r\n")[0].decode()
        self.accept = re.search(rb"Sec-WebSocket-Accept: (\S+)", head).group(1).decode()
        self.key = key

    def send(self, obj) -> None:
        data = json.dumps(obj).encode()
        mask = os.urandom(4)
        head = struct.pack(">BB", 0x81, 0x80 | len(data)) if len(data) < 126 else \
            struct.pack(">BBH", 0x81, 0x80 | 126, len(data))
        self.s.sendall(head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def read_until(self, pattern: bytes, timeout: float = 20) -> bytes:
        out = b""
        end = time.time() + timeout
        self.s.settimeout(0.5)
        while time.time() < end and not re.search(pattern, out):
            try:
                b0, b1 = self._read(2)
            except socket.timeout:
                continue
            n = b1 & 0x7F
            if n == 126:
                (n,) = struct.unpack(">H", self._read(2))
            elif n == 127:
                (n,) = struct.unpack(">Q", self._read(8))
            self.s.settimeout(5)
            out += self._read(n)
            self.s.settimeout(0.5)
        return out

    def close(self) -> None:
        self.s.close()

    def _read(self, n: int) -> bytes:
        b = b""
        while len(b) < n:
            c = self.s.recv(n - len(b))
            if not c:
                raise ConnectionError
            b += c
        return b


def test_accept_key_matches_rfc_example():
    assert WebSocket.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


@pytest.fixture()
def gateway(tmp_path, monkeypatch):
    import theempire.web as web
    monkeypatch.setattr(web, "WEB_HOMES", tmp_path / "homes")
    game = Game("coldwar", humans=("nato", "pact"), seed=5, world=load_world())
    srv = GameServer(game, "127.0.0.1", 0, password="pw", log=lambda line: None)
    srv.listen()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    gw = WebGateway(("127.0.0.1", srv.port), "127.0.0.1", 0, srv.web_info, log=lambda line: None,
                    prepare_sounds=False)
    gw.listen()
    threading.Thread(target=gw.serve_forever, daemon=True).start()
    yield gw, srv
    gw.stop()
    srv.stop()


def get(gw, path):
    return urllib.request.urlopen(f"http://127.0.0.1:{gw.port}{path}", timeout=10)


def test_page_assets_and_info(gateway):
    gw, _ = gateway
    page = get(gw, "/tui").read()
    assert b"vendor/xterm.js" in page and b"registerOscHandler(7777" in page
    assert b"<canvas" in get(gw, "/").read()             # the graphical map is the home page
    assert len(get(gw, "/vendor/xterm.js").read()) > 100_000
    info = json.loads(get(gw, "/info").read())
    assert [s["key"] for s in info["seats"]] == ["nato", "pact"] and info["password"]
    for bad in ("/vendor/../web.py", "/sounds/../../x", "/etc/passwd"):
        with pytest.raises(urllib.error.HTTPError):
            get(gw, bad)


def test_browser_session_plays_the_game(gateway):
    gw, srv = gateway
    ws = WSClient(gw.port, f"/ws?name=Anna&faction=nato&id={os.urandom(16).hex()}&cols=130&rows=42")
    assert "101" in ws.status
    assert ws.accept == WebSocket.accept_key(ws.key)
    ws.send({"t": "p", "d": "pw"})
    out = ws.read_until(rb"In attesa degli altri giocatori")
    assert b"In attesa degli altri giocatori" in out
    # the lobby tune travels to the browser as an invisible OSC sequence
    if not re.search(rb"\x1b\]7777;music;menu;1\x07", out):
        out += ws.read_until(rb"\x1b\]7777;music;menu;1\x07")
    assert re.search(rb"\x1b\]7777;music;menu;1\x07", out)
    assert srv.slots[0].name == "Anna"
    ws.send({"t": "r", "c": 140, "r": 44})
    ws.send({"t": "i", "d": "Q"})
    ws.close()


def test_wrong_password_is_shown_in_the_terminal(gateway):
    gw, _ = gateway
    ws = WSClient(gw.port, f"/ws?name=X&faction=pact&id={os.urandom(16).hex()}")
    ws.send({"t": "p", "d": "sbagliata"})
    assert b"password errata" in ws.read_until(rb"password errata")
    ws.close()


def test_bad_browser_id_is_refused(gateway):
    gw, _ = gateway
    ws = WSClient(gw.port, "/ws?name=X&id=../../etc")
    ws.send({"t": "p", "d": ""})
    with pytest.raises(ConnectionError):   # closed at once, no game client started
        ws.read_until(rb"THE EMPIRE", timeout=5)
    ws.close()


def test_language_reaches_the_client(gateway, monkeypatch):
    import theempire.web as web
    envs = []

    def fake_popen(argv, env=None, **kw):
        envs.append(env)
        raise OSError("no client in this test")
    monkeypatch.setattr(web.subprocess, "Popen", fake_popen)
    gw, _ = gateway
    for lang in ("en", "xx"):
        ws = WSClient(gw.port, f"/ws?name=X&lang={lang}&id={os.urandom(16).hex()}")
        ws.send({"t": "p", "d": ""})
        with pytest.raises(ConnectionError):
            ws.read_until(rb"THE EMPIRE", timeout=5)
        ws.close()
    # an unknown language falls back to the server's own
    assert [e["THEEMPIRE_LANG"] for e in envs] == ["en", web.i18n.language()]
