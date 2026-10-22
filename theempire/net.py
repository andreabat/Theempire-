"""Online multiplayer: an authoritative TCP server and its client session.

Protocol: every message is a 4-byte big-endian length followed by a
zlib-compressed JSON object. Clients only ever send commands; the server
validates them with ``commands.apply``, plays the AI factions, and sends each
player the state filtered by that player's fog of war.

    client -> server  {"type": "hello", "version", "name", "faction", "token", "password"}
                      {"type": "cmd", "id", "cmd": {...}}
    server -> client  {"type": "welcome", "faction", "token"}
                      {"type": "state", "state", "lobby", "started", "deadline"}
                      {"type": "result", "id", "result"}
                      {"type": "error", "message"}
"""

from __future__ import annotations

import hmac
import json
import secrets
import socket
import struct
import threading
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from theempire import commands
from theempire.game import Game
from theempire.i18n import Msg, tr, word

PROTOCOL = 1
DEFAULT_PORT = 7777
MAX_CLIENT_MESSAGE = 64 * 1024          # commands are tiny
MAX_SERVER_MESSAGE = 64 * 1024 * 1024   # full game states
TOKENS_FILE = Path.home() / ".theempire" / "online.json"


class ProtocolError(Exception):
    pass


# ------------------------------------------------------------------ framing
def send_msg(sock: socket.socket, obj: dict) -> None:
    data = zlib.compress(json.dumps(obj, separators=(",", ":")).encode("utf-8"))
    sock.sendall(struct.pack(">I", len(data)) + data)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(65536, n - len(buf)))
        if not chunk:
            raise ConnectionError(tr("connessione chiusa"))
        buf += chunk
    return bytes(buf)


def recv_msg(sock: socket.socket, limit: int) -> dict:
    (n,) = struct.unpack(">I", _recv_exact(sock, 4))
    if n > limit:
        raise ProtocolError(tr("messaggio troppo grande"))
    z = zlib.decompressobj()
    raw = z.decompress(_recv_exact(sock, n), limit * 8)
    if z.unconsumed_tail:
        raise ProtocolError(tr("messaggio troppo grande"))
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(tr("messaggio non valido")) from exc
    if not isinstance(obj, dict):
        raise ProtocolError(tr("messaggio non valido"))
    return obj


# ------------------------------------------------------------------- server
@dataclass
class Slot:
    faction: int
    name: str = ""
    token: str = ""
    conn: "Connection | None" = None


@dataclass
class Connection:
    sock: socket.socket
    address: str
    slot: Slot | None = None
    watching: int | None = None         # a map page: the faction whose view it gets
    send_lock: threading.Lock = field(default_factory=threading.Lock)

    def send(self, obj: dict) -> bool:
        try:
            with self.send_lock:
                send_msg(self.sock, obj)
            return True
        except OSError:
            return False

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class GameServer:
    """Hosts one game. Human factions are seats for online players; every
    other faction is played by the AI on the server."""

    def __init__(self, game: Game, host: str = "0.0.0.0", port: int = DEFAULT_PORT,
                 password: str = "", save_path: Path | None = None,
                 turn_time: int = 0, log: Callable[[str], None] = print,
                 resume: bool = True):
        self.game = game
        self.host, self.port = host, port
        self.password = password
        self.save_path = save_path
        self.turn_time = turn_time
        self.log = log
        self.lock = threading.RLock()
        self.slots = {f.idx: Slot(f.idx) for f in game.factions if f.human}
        if not self.slots:
            raise ValueError(tr("serve almeno una fazione umana"))
        self.started = False
        self.reels: dict[int, list[dict]] = {}   # bulletins waiting for their player
        self.turn_key: tuple[int, int] | None = None
        self.turn_started = time.time()
        self.stopping = threading.Event()
        self.sock: socket.socket | None = None
        self.last_pulse = time.time()   # real time: when the last pulse came
        self.watchers: list[Connection] = []   # map pages, each on a player's seat
        if resume:              # a saved game: its players get their seats back
            self._load_slots()
        else:                   # a new game: every seat is free again
            path = self._slots_path()
            if path is not None and path.exists():
                path.unlink()

    # -- persistence of seats, so players can rejoin a restarted server
    def _slots_path(self) -> Path | None:
        return self.save_path.with_suffix(".seats.json") if self.save_path else None

    def _load_slots(self) -> None:
        path = self._slots_path()
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for key, seat in data.get("seats", {}).items():
            slot = self.slots.get(int(key))
            if slot is not None and data.get("scenario") == self.game.scenario.key:
                slot.name, slot.token = seat.get("name", ""), seat.get("token", "")
        self.started = all(s.token for s in self.slots.values()) and self.game.turn > 1

    def save(self) -> None:
        if self.save_path is None:
            return
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.game.save_file(self.save_path)
        seats = {str(k): {"name": s.name, "token": s.token} for k, s in self.slots.items()}
        self._slots_path().write_text(json.dumps(
            {"scenario": self.game.scenario.key, "seats": seats}), encoding="utf-8")

    # -- networking
    def listen(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(16)
        self.sock = sock
        self.port = sock.getsockname()[1]
        return self.port

    def serve_forever(self) -> None:
        if self.sock is None:
            self.listen()
        threading.Thread(target=self._timer, daemon=True).start()
        self.log(tr("Server in ascolto su {address} · {scenario} · posti: {seats}",
                    address=f"{self.host}:{self.port}", scenario=self.game.scenario.name,
                    seats=", ".join(word(self.game.factions[f].name) for f in self.slots)))
        while not self.stopping.is_set():
            try:
                client, addr = self.sock.accept()
            except OSError:
                break
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn = Connection(client, f"{addr[0]}:{addr[1]}")
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def stop(self) -> None:
        self.stopping.set()
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        with self.lock:
            for slot in self.slots.values():
                if slot.conn is not None:
                    slot.conn.close()

    def _client(self, conn: Connection) -> None:
        try:
            conn.sock.settimeout(15)
            hello = recv_msg(conn.sock, MAX_CLIENT_MESSAGE)
            conn.sock.settimeout(None)
            if not self._join(conn, hello):
                conn.close()
                return
            while True:
                msg = recv_msg(conn.sock, MAX_CLIENT_MESSAGE)
                if msg.get("type") == "cmd" and isinstance(msg.get("cmd"), dict) and conn.slot:
                    self._command(conn, msg)
        except (ConnectionError, ProtocolError, OSError, socket.timeout, struct.error):
            pass
        finally:
            self._leave(conn)

    def _join(self, conn: Connection, hello: dict) -> bool:
        if hello.get("type") != "hello" or hello.get("version") != PROTOCOL:
            conn.send({"type": "error", "message": tr("versione del gioco diversa da quella del server")})
            return False
        if hello.get("watch"):      # the seat token is the proof: it was given after the password
            return self._watch(conn, str(hello.get("token") or ""))
        if self.password and not hmac.compare_digest(str(hello.get("password", "")), self.password):
            conn.send({"type": "error", "message": tr("password errata")})
            return False
        name = commands.printable(str(hello.get("name") or ""))[:24].strip() or "Giocatore"
        token = str(hello.get("token") or "")
        wanted = hello.get("faction")
        with self.lock:
            slot = None
            if token:
                slot = next((s for s in self.slots.values()
                             if s.token and hmac.compare_digest(s.token, token)), None)
            if slot is None and wanted:
                slot = next((s for s in self.slots.values()
                             if self.game.factions[s.faction].key == wanted), None)
                if slot is None:
                    conn.send({"type": "error", "message": tr("la fazione {faction} non è un posto libero", faction=str(wanted))})
                    return False
                if slot.token:
                    conn.send({"type": "error", "message": tr("posto già occupato da un altro giocatore")})
                    return False
            if slot is None:
                slot = next((s for s in self.slots.values() if not s.token), None)
                if slot is None:
                    conn.send({"type": "error", "message": tr("la partita è al completo")})
                    return False
            if slot.conn is not None and slot.conn is not conn:
                slot.conn.close()  # the same player reconnecting
            if not slot.token:
                slot.token = secrets.token_hex(16)
            slot.name, slot.conn, conn.slot = name, conn, slot
            conn.send({"type": "welcome", "faction": slot.faction, "token": slot.token,
                       "faction_key": self.game.factions[slot.faction].key})
            self.log(tr("{name} ({address}) gioca con {faction}", name=name, address=conn.address,
                        faction=self.game.factions[slot.faction].name))
            if not self.started and all(s.token for s in self.slots.values()):
                self.started = True
                self.log(tr("Tutti i giocatori sono arrivati: si comincia."))
                if self.game.realtime:
                    self.last_pulse = time.time()
                else:
                    commands.advance(self.game)
            self._broadcast()
        return True

    def _watch(self, conn: Connection, token: str) -> bool:
        """A map page (web.py) following the game with the eyes of a seat
        it holds the token of. It only reads: its commands are ignored."""
        with self.lock:
            slot = next((s for s in self.slots.values()
                         if token and s.token and hmac.compare_digest(s.token, token)), None)
            if slot is None:
                conn.send({"type": "error", "message": tr("nessun posto con questo gettone")})
                return False
            conn.watching = slot.faction
            self.watchers.append(conn)
            conn.send({"type": "welcome", "faction": slot.faction, "watch": True,
                       "faction_key": self.game.factions[slot.faction].key})
            conn.send(self._state_for(slot.faction))
        return True

    def _state_for(self, f: int) -> dict:
        return {"type": "state", "state": commands.view_for(self.game, f), "lobby": self.lobby(),
                "started": self.started, "deadline": self._deadline()}

    def _leave(self, conn: Connection) -> None:
        with self.lock:
            if conn in self.watchers:
                self.watchers.remove(conn)
            slot = conn.slot
            if slot is not None and slot.conn is conn:
                slot.conn = None
                self.log(tr("{name} si è disconnesso ({faction})", name=slot.name,
                            faction=self.game.factions[slot.faction].name))
                self._broadcast()
        conn.close()

    def _command(self, conn: Connection, msg: dict) -> None:
        cmd = msg["cmd"]
        with self.lock:
            f = conn.slot.faction
            if cmd.get("op") == "save":
                self.save()
                result = "saved" if self.save_path else "nosave"
            elif not self.started and cmd.get("op") != "chat":
                result = "waiting"
            else:
                before = self.game.turn
                result = commands.apply(self.game, f, cmd, name=conn.slot.name)
                if self.game.turn != before or self.game.over:
                    self.save()
            self._broadcast()
        conn.send({"type": "result", "id": msg.get("id"), "result": result})

    def web_info(self) -> dict:
        """What the web page shows before joining: seats, AI factions, state."""
        with self.lock:
            g = self.game
            seats = [{"key": g.factions[s.faction].key, "faction": g.factions[s.faction].name,
                      "name": s.name, "taken": bool(s.token), "online": s.conn is not None}
                     for s in self.slots.values()]
            return {"scenario": g.scenario.name, "started": self.started, "seats": seats,
                    "ai": [f.name for f in g.factions if not f.human],
                    "password": bool(self.password)}

    def lobby(self) -> list[dict]:
        return [{"faction": s.faction, "name": s.name, "taken": bool(s.token),
                 "online": s.conn is not None} for s in self.slots.values()]

    def _deadline(self) -> float | None:
        if not self.started or self.game.over:
            return None
        if self.game.realtime:        # the countdown to the next pulse
            return max(0.0, self.game.realtime - (time.time() - self.last_pulse))
        if not self.turn_time:
            return None
        return max(0.0, self.turn_time - (time.time() - self.turn_started))

    def _broadcast(self) -> None:
        key = (self.game.turn, self.game.current)
        if key != self.turn_key:
            self.turn_key = key
            self.turn_started = time.time()
            f = self.game.current
            if self.started and self.game.realtime and not self.game.over:
                for s in self.slots:        # real time: everybody hears the news of the pulse
                    self.reels[s] = self.reels.get(s, []) + commands.newsreel(self.game, s)
            elif self.started and f in self.slots and not self.game.over:
                # the war bulletin: what happened since this player's last turn
                self.reels[f] = self.reels.get(f, []) + commands.newsreel(self.game, f)
        lobby = self.lobby()
        for slot in self.slots.values():
            if slot.conn is not None:
                msg = {"type": "state", "state": commands.view_for(self.game, slot.faction),
                       "lobby": lobby, "started": self.started, "deadline": self._deadline()}
                reel = self.reels.get(slot.faction)
                if reel and (self.game.current == slot.faction or self.game.realtime):
                    msg["reel"] = reel
                if slot.conn.send(msg) and reel and "reel" in msg:
                    self.reels.pop(slot.faction, None)
        views: dict[int, dict] = {}
        for conn in list(self.watchers):
            f = conn.watching
            if f not in views:
                views[f] = self._state_for(f)
            if not conn.send(views[f]):
                self.watchers.remove(conn)

    def _pulse(self) -> None:
        """Real time: the next pulse for everybody when its time has come."""
        with self.lock:
            if not self.started or self.game.over or time.time() - self.last_pulse < self.game.realtime:
                return
            commands.tick(self.game)
            self.last_pulse = time.time()
            self.save()
            self._broadcast()

    def _timer(self) -> None:
        while not self.stopping.wait(1.0):
            if self.game.realtime:
                self._pulse()
                continue
            if not self.turn_time:
                continue
            with self.lock:
                if not self.started or self.game.over or not self.game.faction.human:
                    continue
                if time.time() - self.turn_started >= self.turn_time:
                    f = self.game.current
                    self.game.log(Msg("Tempo scaduto per {faction}.", faction=self.game.factions[f].name),
                                  None, "alert")
                    commands.apply(self.game, f, {"op": "end_turn"})
                    self.save()
                    self._broadcast()


# ------------------------------------------------------------------- client
class RemoteSession:
    """The client side: the same interface as a local session, but every
    command travels to the server and the game is replaced by the state the
    server sends back."""

    online = True

    def __init__(self, host: str, port: int, name: str, faction: str | None = None,
                 password: str = "", tokens_file: Path | None = TOKENS_FILE, timeout: float = 15):
        self.address = f"{host}:{port}"
        self.tokens_file = tokens_file
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        send_msg(self.sock, {"type": "hello", "version": PROTOCOL, "name": name,
                             "faction": faction, "token": self._stored_token(faction),
                             "password": password})
        reply = recv_msg(self.sock, MAX_SERVER_MESSAGE)
        if reply.get("type") == "error":
            self.sock.close()
            raise ConnectionError(reply.get("message") or tr("rifiutato dal server"))
        if reply.get("type") != "welcome":
            raise ProtocolError(tr("risposta inattesa dal server"))
        self.faction: int = reply["faction"]
        self._store_token(reply.get("faction_key", ""), reply["token"])
        first = recv_msg(self.sock, MAX_SERVER_MESSAGE)
        if first.get("type") != "state":
            raise ProtocolError(tr("risposta inattesa dal server"))
        self.sock.settimeout(None)
        self.game = Game.from_dict(first["state"])
        self.lobby: list[dict] = first.get("lobby", [])
        self.started: bool = bool(first.get("started"))
        self.deadline: float | None = first.get("deadline")
        self.deadline_at = time.time()
        self.closed = False
        self.error = ""
        self.reel: list[dict] = []
        self._pending: dict | None = None
        self._results: dict[int, str] = {}
        self._next = 0
        self._cond = threading.Condition()
        threading.Thread(target=self._reader, daemon=True).start()

    def _tokens(self) -> dict:
        if self.tokens_file is None or not self.tokens_file.exists():
            return {}
        try:
            data = json.loads(self.tokens_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _stored_token(self, faction: str | None) -> str:
        """The seat token kept from an earlier visit to this server: for the
        requested faction, or the only seat we hold there."""
        seats = self._tokens().get(self.address)
        if not isinstance(seats, dict):
            return ""
        if faction:
            return str(seats.get(faction, ""))
        return str(next(iter(seats.values()))) if len(seats) == 1 else ""

    def _store_token(self, faction_key: str, token: str) -> None:
        if self.tokens_file is None:
            return
        data = self._tokens()
        seats = data.get(self.address)
        if not isinstance(seats, dict):
            seats = {}
        seats[faction_key] = token
        data[self.address] = seats
        self.tokens_file.parent.mkdir(parents=True, exist_ok=True)
        self.tokens_file.write_text(json.dumps(data), encoding="utf-8")

    def _reader(self) -> None:
        try:
            while True:
                msg = recv_msg(self.sock, MAX_SERVER_MESSAGE)
                with self._cond:
                    if msg.get("type") == "state":
                        self._pending = msg
                    elif msg.get("type") == "result":
                        self._results[msg.get("id")] = msg.get("result", "")
                    elif msg.get("type") == "error":
                        self.error = msg.get("message", "")
                    self._cond.notify_all()
        except (ConnectionError, ProtocolError, OSError, struct.error):
            pass
        with self._cond:
            self.closed = True
            self._cond.notify_all()

    def poll(self) -> bool:
        """Apply the newest state from the server; True if something changed."""
        with self._cond:
            msg, self._pending = self._pending, None
        if msg is None:
            return False
        self.game = Game.from_dict(msg["state"])
        if msg.get("reel"):
            self.reel = msg["reel"]
        self.lobby = msg.get("lobby", self.lobby)
        self.started = bool(msg.get("started"))
        self.deadline = msg.get("deadline")
        self.deadline_at = time.time()
        return True

    def take_reel(self, f: int) -> list[dict]:
        """The bulletin the server sent with this turn (once)."""
        reel, self.reel = self.reel, []
        return reel

    def seconds_left(self) -> int | None:
        if self.deadline is None:
            return None
        return max(0, int(self.deadline - (time.time() - self.deadline_at)))

    def do(self, f: int, cmd: dict, progress=None, timeout: float = 600) -> str:
        with self._cond:
            if self.closed:
                return "disconnected"
            self._next += 1
            rid = self._next
        try:
            send_msg(self.sock, {"type": "cmd", "id": rid, "cmd": cmd})
        except OSError:
            return "disconnected"
        end = time.time() + timeout
        with self._cond:
            while rid not in self._results and not self.closed and time.time() < end:
                if progress:
                    progress(tr("il server"))
                self._cond.wait(0.5)
            result = self._results.pop(rid, "disconnected")
        self.poll()
        return result

    def player_names(self) -> dict[int, str]:
        return {s["faction"]: s["name"] + ("" if s["online"] else " (offline)")
                for s in self.lobby if s["taken"]}

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class LocalSession:
    """A game played on this computer (alone or hot-seat)."""

    online = False
    started = True
    closed = False
    error = ""

    def __init__(self, game: Game, save_path: Path, turn_time: int = 0):
        self.game = game
        self.save_path = save_path
        self.faction = None
        self.turn_time = turn_time      # seconds per human turn, 0 = no limit
        self.clock_started: float | None = None
        self.last_pulse = time.time()   # real time: when the last pulse came

    def do(self, f: int, cmd: dict, progress=None) -> str:
        if cmd.get("op") == "save":
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            self.game.save_file(self.save_path)
            return "saved"
        result = commands.apply(self.game, f, cmd, progress=progress)
        if self.game.realtime and cmd.get("op") == "end_turn" and result == "ok":
            self.last_pulse = time.time()
        return result

    def start(self, progress=None) -> None:
        if self.game.realtime:
            self.last_pulse = time.time()
        else:
            commands.advance(self.game, progress)

    def poll(self) -> bool:
        """Real time: the next pulse when its time has come (while a menu
        is open nothing is polled, so the war waits)."""
        g = self.game
        if not g.realtime or g.over or time.time() - self.last_pulse < g.realtime:
            return False
        commands.tick(g)
        self.last_pulse = time.time()
        return True

    def take_reel(self, f: int) -> list[dict]:
        return commands.newsreel(self.game, f)

    def start_clock(self) -> None:
        """A human turn begins: the turn timer, if any, starts counting."""
        self.clock_started = time.time() if self.turn_time else None

    def seconds_left(self) -> int | None:
        if self.game.over:
            return None
        if self.game.realtime:
            return max(0, int(self.game.realtime - (time.time() - self.last_pulse)))
        if not self.turn_time or self.clock_started is None:
            return None
        return max(0, int(self.turn_time - (time.time() - self.clock_started)))

    def player_names(self) -> dict[int, str]:
        return {}

    def close(self) -> None:
        pass
