"""The web TUI: play The Empire in a browser.

A small HTTP + WebSocket gateway (standard library only). For every browser
that connects it starts a normal online client (``--join``) in a
pseudo-terminal, and streams that terminal to the page, where xterm.js draws
it: same Braille map, colours, keys and mouse as in a real terminal. Sound
cues reach the page as invisible OSC 7777 escape sequences and the browser
plays them from ``/sounds``.

Every browser has a random id (kept in its localStorage); its client runs
with its own home folder, so seat tokens and audio choices belong to that
browser and a reload puts the player back in their seat.
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

from theempire import audio
from theempire.commands import printable

PAGE = Path(__file__).resolve().parent / "assets" / "web" / "index.html"
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
        self.log(f"Web TUI su http://{self.host}:{self.port}/ → partita {self.target[0]}:{self.target[1]}")
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
            if name in audio._SFX_NAMES + audio._MUSIC_NAMES and wav.exists():
                self._reply(req, wav.read_bytes(), "audio/wav", cache=True)
            else:
                req.send_error(HTTPStatus.NOT_FOUND)
        elif path == "/ws":
            self._websocket(req, parse_qs(url.query))
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
    def _websocket(self, req: BaseHTTPRequestHandler, query: dict) -> None:
        key = req.headers.get("Sec-WebSocket-Key", "")
        if req.headers.get("Upgrade", "").lower() != "websocket" or not key:
            req.send_error(HTTPStatus.BAD_REQUEST)
            return
        with self.lock:
            if self.sessions >= MAX_SESSIONS:
                req.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "troppi giocatori collegati")
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
            self._session(WebSocket(req.connection), query)
        finally:
            with self.lock:
                self.sessions -= 1

    def _session(self, ws: WebSocket, query: dict) -> None:
        def arg(name: str, default: str = "") -> str:
            return (query.get(name) or [default])[0]

        name = printable(arg("name"))[:24].strip() or "Giocatore"
        faction = arg("faction")
        faction = faction if re.fullmatch(r"[a-z]{1,16}", faction) else ""
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
        env = {**os.environ, "HOME": str(home), "TERM": "xterm-256color",
               "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "THEEMPIRE_PASSWORD": password,
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
        self.log(f"web: {name} si collega ({faction or 'posto libero'})")
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
            self.log(f"web: {name} si è scollegato")

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
