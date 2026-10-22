"""The web TUI: play The Empire in a browser.

A small HTTP + WebSocket gateway (standard library only). For every browser
that connects it starts a normal online client (``--join``) in a
pseudo-terminal, and streams that terminal to the page, where xterm.js draws
it: same Braille map, colours, keys and mouse as in a real terminal. Sound
cues reach the page as invisible OSC 7777 escape sequences and the browser
plays them from ``/sounds``.

Every browser has a random id (kept in its localStorage); its client runs
with its own home folder, so seat tokens and audio choices belong to that
browser and a reload puts the player back in their seat. The page also
chooses the language (``lang=`` in the WebSocket URL): the client gets it as
THEEMPIRE_LANG.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import termios
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from theempire import audio, i18n, midi
from theempire.commands import printable
from theempire.i18n import tr

PAGE = Path(__file__).resolve().parent / "assets" / "web" / "index.html"
MAP_PAGE = PAGE.with_name("map.html")        # the graphical map (mapview.py)
WEB_HOMES = Path.home() / ".theempire" / "web"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_FRAME = 1 << 20
MAX_SESSIONS = 24


# --------------------------------------------------------------- websocket
class WebSocket:
    """The server side of RFC 6455, just enough for a terminal stream."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.lock = threading.Lock()
        self.closed = False

    @staticmethod
    def accept_key(key: str) -> str:
        return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()

    def _read(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return bytes(buf)

    def recv(self) -> str | bytes | None:
        """Next complete message; None when the peer closes."""
        parts: list[bytes] = []
        opcode = None
        while True:
            b0, b1 = self._read(2)
            fin, op = b0 & 0x80, b0 & 0x0F
            length = b1 & 0x7F
            if length == 126:
                (length,) = struct.unpack(">H", self._read(2))
            elif length == 127:
                (length,) = struct.unpack(">Q", self._read(8))
            if length > MAX_FRAME or sum(map(len, parts)) + length > MAX_FRAME:
                raise ConnectionError("frame too large")
            if not b1 & 0x80:
                raise ConnectionError("client frames must be masked")
            mask = self._read(4)
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(self._read(length)))
            if op == 0x8:
                self.close()
                return None
            if op == 0x9:
                self._send(0xA, data)
                continue
            if op == 0xA:
                continue
            if op in (0x1, 0x2):
                opcode = op
            parts.append(data)
            if fin:
                payload = b"".join(parts)
                return payload.decode("utf-8", "replace") if opcode == 0x1 else payload

    def _send(self, opcode: int, data: bytes) -> None:
        n = len(data)
        if n < 126:
            head = struct.pack(">BB", 0x80 | opcode, n)
        elif n < 1 << 16:
            head = struct.pack(">BBH", 0x80 | opcode, 126, n)
        else:
            head = struct.pack(">BBQ", 0x80 | opcode, 127, n)
        with self.lock:
            self.sock.sendall(head + data)

    def send_bytes(self, data: bytes) -> None:
        self._send(0x2, data)

    def send_text(self, text: str) -> None:
        self._send(0x1, text.encode("utf-8"))

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self._send(0x8, b"")
        except OSError:
            pass


# ----------------------------------------------------------------- gateway
class WebGateway:
    """Serves the page and bridges each browser to a terminal client."""

    def __init__(self, target: tuple[str, int], host: str = "0.0.0.0", port: int = 8080,
                 info: Callable[[], dict] | None = None, log: Callable[[str], None] = print):
        self.target = target
        self.host, self.port = host, port
        self.info = info or (lambda: {})
        self.log = log
        self.sessions = 0
        self.lock = threading.Lock()
        self.httpd: ThreadingHTTPServer | None = None
        self.sounds_ready = threading.Event()
        threading.Thread(target=self._sounds, daemon=True).start()

    def _sounds(self) -> None:
        try:
            audio.generate(audio.CACHE)
        except OSError:
            pass
        self.sounds_ready.set()

    def listen(self) -> int:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "TheEmpire"
            # RFC 6455 requires the 101 upgrade response in HTTP/1.1 (or higher).
            # The BaseHTTPRequestHandler default (HTTP/1.0) makes strict clients
            # like Firefox refuse the WebSocket handshake.
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # keep the console quiet
                pass

            def do_GET(self):
                gateway.handle(self)

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        return self.port

    def serve_forever(self) -> None:
        if self.httpd is None:
            self.listen()
        self.log(tr("Web TUI su {url} → partita {address}", url=f"http://{self.host}:{self.port}/",
                    address=f"{self.target[0]}:{self.target[1]}"))
        self.httpd.serve_forever()

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()

    # -- HTTP
    def handle(self, req: BaseHTTPRequestHandler) -> None:
        url = urlparse(req.path)
        path = url.path.rstrip("/") or "/"
        if path == "/":
            self._reply(req, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path.startswith("/vendor/"):
            name = path[len("/vendor/"):]
            types = {"xterm.js": "text/javascript", "xterm-addon-fit.js": "text/javascript",
                     "xterm.css": "text/css"}
            if name in types:
                self._reply(req, (PAGE.parent / "vendor" / name).read_bytes(),
                            types[name] + "; charset=utf-8", cache=True)
            else:
                req.send_error(HTTPStatus.NOT_FOUND)
        elif path == "/favicon.ico":
            req.send_response(HTTPStatus.NO_CONTENT)
            req.end_headers()
        elif path == "/info":
            self._reply(req, json.dumps(self.info()).encode(), "application/json")
        elif path.startswith("/sounds/"):
            name = path[len("/sounds/"):].removesuffix(".wav")
            self.sounds_ready.wait(30)  # the first visitors may beat the synthesiser
            wav = audio.CACHE / f"{name}.wav"
            known = audio._SFX_NAMES + audio._MUSIC_NAMES + tuple(audio.user_tracks())
            if name in known and wav.exists():
                self._reply(req, wav.read_bytes(), "audio/wav", cache=True)
            else:
                req.send_error(HTTPStatus.NOT_FOUND)
        elif path == "/ws":
            self._websocket(req, parse_qs(url.query))
        elif path == "/map":
            self._reply(req, MAP_PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/map/world.json":
            from theempire import mapview
            hexgrid = (parse_qs(url.query).get("hex") or ["0"])[0] == "1"
            self._reply(req, json.dumps(mapview.world(hexgrid)).encode(), "application/json")
        elif path == "/map/land.png":
            from theempire import mapview
            png = mapview.land_png()
            if png is None:
                req.send_error(HTTPStatus.NOT_FOUND)
            else:
                self._reply(req, png, "image/png", cache=True)
        elif path == "/map/ws":
            self._websocket(req, parse_qs(url.query), self._map_session)
        else:
            req.send_error(HTTPStatus.NOT_FOUND)

    @staticmethod
    def _reply(req, body: bytes, ctype: str, cache: bool = False) -> None:
        req.send_response(HTTPStatus.OK)
        req.send_header("Content-Type", ctype)
        req.send_header("Content-Length", str(len(body)))
        req.send_header("Cache-Control", "max-age=86400" if cache else "no-cache")
        req.send_header("X-Content-Type-Options", "nosniff")
        req.end_headers()
        req.wfile.write(body)

    # -- one browser
    def _websocket(self, req: BaseHTTPRequestHandler, query: dict, session=None) -> None:
        key = req.headers.get("Sec-WebSocket-Key", "")
        if req.headers.get("Upgrade", "").lower() != "websocket" or not key:
            req.send_error(HTTPStatus.BAD_REQUEST)
            return
        with self.lock:
            if self.sessions >= MAX_SESSIONS:
                req.send_error(HTTPStatus.SERVICE_UNAVAILABLE,
                               explain=tr("troppi giocatori collegati"))
                return
            self.sessions += 1
        try:
            req.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
            req.send_header("Upgrade", "websocket")
            req.send_header("Connection", "Upgrade")
            req.send_header("Sec-WebSocket-Accept", WebSocket.accept_key(key))
            req.end_headers()
            req.wfile.flush()
            req.close_connection = True
            (session or self._session)(WebSocket(req.connection), query)
        finally:
            with self.lock:
                self.sessions -= 1

    def _session(self, ws: WebSocket, query: dict) -> None:
        def arg(name: str, default: str = "") -> str:
            return (query.get(name) or [default])[0]

        name = printable(arg("name"))[:24].strip() or tr("Giocatore")
        faction = arg("faction")
        faction = faction if re.fullmatch(r"[a-z]{1,16}", faction) else ""
        lang = arg("lang")
        lang = lang if lang in i18n.LANGS else i18n.language()
        browser = arg("id")
        if not re.fullmatch(r"[0-9a-f]{32}", browser):
            ws.close()
            return
        cols = _clamp(arg("cols", "120"), 40, 400)
        rows = _clamp(arg("rows", "40"), 15, 200)
        password = ""
        try:  # the page sends the password as its first message, never in the URL
            first = ws.recv()
            if isinstance(first, str):
                msg = json.loads(first)
                if msg.get("t") == "p":
                    password = str(msg.get("d", ""))[:64]
        except (ConnectionError, OSError, ValueError):
            return
        home = WEB_HOMES / browser
        home.mkdir(parents=True, exist_ok=True)
        argv = [sys.executable, "-m", "theempire", "--join", f"{self.target[0]}:{self.target[1]}",
                "--name", name, "--audio-web"]
        if faction:
            argv += ["--faction", faction]
        # the browsers hear the music folder of whoever runs the server
        env = {**os.environ, "HOME": str(home), "TERM": "xterm-256color",
               "THEEMPIRE_MUSIC": str(midi.music_dir()),
               "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "THEEMPIRE_PASSWORD": password,
               "THEEMPIRE_LANG": lang,
               "PYTHONPATH": str(Path(__file__).resolve().parents[1]) + os.pathsep
               + os.environ.get("PYTHONPATH", "")}
        # A pseudo-terminal for the client. subprocess (not pty.fork) keeps
        # this safe in a multi-threaded server.
        fd, slave = pty.openpty()
        _set_size(fd, cols, rows)
        try:
            proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env,
                                    start_new_session=True, close_fds=True)
        except OSError:
            os.close(fd)
            os.close(slave)
            ws.close()
            return
        os.close(slave)
        self.log(tr("web: {name} si collega ({seat})", name=name,
                    seat=faction or tr("posto libero")))
        reader = threading.Thread(target=self._pump, args=(fd, ws), daemon=True)
        reader.start()
        try:
            while True:
                msg = ws.recv()
                if msg is None:
                    break
                if not isinstance(msg, str):
                    continue
                try:
                    data = json.loads(msg)
                except ValueError:
                    continue
                if data.get("t") == "i":
                    text = str(data.get("d", ""))
                    if text:
                        os.write(fd, text.encode("utf-8"))
                elif data.get("t") == "r":
                    _set_size(fd, _clamp(data.get("c"), 40, 400), _clamp(data.get("r"), 15, 200))
                    proc.send_signal(signal.SIGWINCH)  # curses re-reads the size
        except (ConnectionError, OSError):
            pass
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGHUP)
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            try:
                os.close(fd)
            except OSError:
                pass
            ws.close()
            self.log(tr("web: {name} si è scollegato", name=name))

    # -- one map page
    def _map_session(self, ws: WebSocket, query: dict) -> None:
        """The graphical map of a browser: it follows the game with the eyes
        of a seat, and gives its orders. The seat is the one this browser
        holds (its terminal client keeps the token), or the one whose token
        the page brings (the link a terminal player gets with W)."""
        from theempire import mapview
        from theempire.net import MAX_SERVER_MESSAGE, PROTOCOL, recv_msg, send_msg

        browser = (query.get("id") or [""])[0]
        lang = (query.get("lang") or [""])[0]
        lang = lang if lang in i18n.LANGS else i18n.language()
        seat = ""
        try:  # the page's first message: the token of the link, if it came with one
            first = json.loads(ws.recv() or "{}")
            if isinstance(first, dict) and re.fullmatch(r"[0-9a-f]{32}", str(first.get("seat", ""))):
                seat = first["seat"]
        except (ConnectionError, OSError, ValueError):
            return
        if not seat and not re.fullmatch(r"[0-9a-f]{32}", browser):
            ws.close()
            return
        gone = threading.Event()
        server: list[socket.socket] = []
        shared: dict = {}                       # the last game and viewer, for the routes
        cards_sent: dict = {}                   # command id -> card played, for its message

        def reply(obj: dict) -> None:
            try:
                ws.send_text(json.dumps(obj, separators=(",", ":")))
            except OSError:
                gone.set()

        def listen() -> None:           # what the page asks: orders and routes
            try:
                while True:
                    msg = ws.recv()
                    if msg is None:
                        break
                    try:
                        data = json.loads(msg)
                    except ValueError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    if data.get("t") == "cmd" and server:
                        cmd = mapview.command(data.get("cmd"))
                        if cmd is not None and cmd["op"] == "card":
                            cards_sent[data.get("id")] = str(cmd.get("card", ""))
                        if cmd is None:
                            reply({"t": "result", "id": data.get("id"), "result": "illegal",
                                   "text": mapview.result_text("illegal", lang)})
                            continue
                        try:
                            send_msg(server[0], {"type": "cmd", "id": data.get("id"), "cmd": cmd})
                        except OSError:
                            pass
                    elif data.get("t") == "path" and "game" in shared:
                        route = mapview.path(shared["game"], shared["viewer"], data.get("unit"),
                                             data.get("cell"))
                        reply({"t": "path", "unit": data.get("unit"), "cell": data.get("cell"),
                               "route": route})
            except (ConnectionError, OSError):
                pass
            gone.set()
            for sock in server:         # wakes the reader below
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        threading.Thread(target=listen, daemon=True).start()
        tokens = WEB_HOMES / browser / ".theempire" / "online.json"
        address = f"{self.target[0]}:{self.target[1]}"
        sent_territory = ""
        try:
            while not gone.is_set():
                token = seat
                if not token:
                    try:
                        seats = json.loads(tokens.read_text(encoding="utf-8")).get(address) or {}
                    except (OSError, ValueError, AttributeError):
                        seats = {}
                    token = next(iter(seats.values()), "") if isinstance(seats, dict) else ""
                if not token:
                    reply({"t": "noseat"})
                    gone.wait(3)
                    continue
                try:
                    sock = socket.create_connection(self.target, timeout=10)
                except OSError:
                    reply({"t": "offline"})
                    gone.wait(3)
                    continue
                try:
                    send_msg(sock, {"type": "hello", "version": PROTOCOL, "watch": True, "token": token})
                    welcome = recv_msg(sock, MAX_SERVER_MESSAGE)
                    if welcome.get("type") != "welcome":
                        reply({"t": "noseat"})
                        gone.wait(3)
                        continue
                    viewer = welcome["faction"]
                    sock.settimeout(None)
                    server[:] = [sock]
                    while not gone.is_set():
                        msg = recv_msg(sock, MAX_SERVER_MESSAGE)
                        if msg.get("type") == "result":
                            result = str(msg.get("result", ""))
                            card = cards_sent.pop(msg.get("id"), None)
                            reply({"t": "result", "id": msg.get("id"), "result": result,
                                   "text": mapview.card_result(card, result, lang) if card is not None
                                   else mapview.result_text(result, lang)})
                            continue
                        if msg.get("type") != "state":
                            continue
                        from theempire.game import Game
                        game = Game.from_dict(msg["state"])
                        shared.update(game=game, viewer=viewer)
                        data = mapview.view_game(game, viewer, lang)
                        if data["territory_key"] == sent_territory:
                            del data["territory"]     # the page has it already
                        sent_territory = data["territory_key"]
                        data["started"] = bool(msg.get("started"))
                        if msg.get("reel"):
                            data["reel"] = mapview.reel(game, msg["reel"], viewer, lang)
                        reply({"t": "state", "d": data})
                except (ConnectionError, OSError, ValueError, KeyError):
                    if not gone.is_set():
                        reply({"t": "offline"})
                        gone.wait(3)
                finally:
                    server.clear()
                    sock.close()
        finally:
            ws.close()

    @staticmethod
    def _pump(fd: int, ws: WebSocket) -> None:
        """Terminal output → browser."""
        try:
            while True:
                r, _, _ = select.select([fd], [], [], 1.0)
                if ws.closed:
                    return
                if not r:
                    continue
                data = os.read(fd, 65536)
                if not data:
                    break
                ws.send_bytes(data)
        except OSError:
            pass
        ws.close()
        try:
            ws.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _clamp(value, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return low


def _set_size(fd: int, cols: int, rows: int) -> None:
    """Tell the terminal its new size (the kernel signals the client)."""
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass
