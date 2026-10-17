"""Curses interface: Braille world map, side panel, event log and menus."""

from __future__ import annotations

import curses
import datetime as dt
import random
import time
from collections import Counter, deque
from pathlib import Path

from theempire.audio import MUSIC_KEYS, MUSIC_NAMES, Audio
from theempire.commands import describe
from theempire.game import CHEM_RANGE, DIRECTIVES, Unit
from theempire.scenarios import SCENARIOS
from theempire.units import (CHEMICAL, PRODUCTION_NAMES, UNIT_TYPES, WARHEAD,
                             production_cost)

SIDEBAR = 36
LOG_ROWS = 6
SAVE_PATH = Path.home() / ".theempire" / "save.json"

START_DATES = {"ww3": dt.date(2027, 3, 1), "coldwar": dt.date(1985, 8, 4)}

DIRECTIONS = {
    ord("q"): (-1, -1), ord("w"): (0, -1), ord("e"): (1, -1),
    ord("a"): (-1, 0), ord("d"): (1, 0),
    ord("z"): (-1, 1), ord("x"): (0, 1), ord("c"): (1, 1),
    ord("7"): (-1, -1), ord("8"): (0, -1), ord("9"): (1, -1),
    ord("4"): (-1, 0), ord("6"): (1, 0),
    ord("1"): (-1, 1), ord("2"): (0, 1), ord("3"): (1, 1),
    curses.KEY_A1: (-1, -1), curses.KEY_A3: (1, -1),
    curses.KEY_C1: (-1, 1), curses.KEY_C3: (1, 1),
}
CURSOR_KEYS = {
    curses.KEY_UP: (0, -1), curses.KEY_DOWN: (0, 1),
    curses.KEY_LEFT: (-1, 0), curses.KEY_RIGHT: (1, 0),
    curses.KEY_SR: (0, -8), curses.KEY_SF: (0, 8),
    curses.KEY_SLEFT: (-16, 0), curses.KEY_SRIGHT: (16, 0),
    curses.KEY_PPAGE: (0, -12), curses.KEY_NPAGE: (0, 12),
}

COLORS_256 = {"blue": 39, "red": 196, "yellow": 220, "green": 46, "cyan": 51,
              "magenta": 207, "orange": 208, "neutral": 107, "white": 255,
              "sea": 17, "coast": 67, "fallout": 226, "dim": 244, "alert": 203,
              "wmd": 201, "good": 120, "panel": 250}
COLORS_8 = {"blue": curses.COLOR_BLUE, "red": curses.COLOR_RED, "yellow": curses.COLOR_YELLOW,
            "green": curses.COLOR_GREEN, "cyan": curses.COLOR_CYAN,
            "magenta": curses.COLOR_MAGENTA, "orange": curses.COLOR_YELLOW,
            "neutral": curses.COLOR_GREEN, "white": curses.COLOR_WHITE, "sea": -1,
            "coast": curses.COLOR_BLUE, "fallout": curses.COLOR_YELLOW,
            "dim": curses.COLOR_WHITE, "alert": curses.COLOR_RED,
            "wmd": curses.COLOR_MAGENTA, "good": curses.COLOR_GREEN, "panel": curses.COLOR_WHITE}

HELP = """\
MOVIMENTO UNITÀ   q w e / a · d / z x c  (o tastierino 7 8 9 4 6 1 2 3)
CURSORE           frecce, PagSu/PagGiù, mouse (trascina o rotella per scorrere)
MOUSE             clic su una tua unità: la selezioni; clic accanto: si muove o
                  attacca; clic lontano: mostra il percorso, secondo clic: parte
Invio             seleziona l'unità sotto il cursore (cicla nelle città)
n / Tab           unità successiva in attesa di ordini
spazio            salta l'unità per questo turno
s                 sentinella (si sveglia se arriva il nemico)
f                 fortifica (+25% difesa, resta di guardia)
A                 automatica: l'unità viene guidata dall'IA
O                 diplomazia: proponi o accetta una tregua
B                 bollettini di guerra: leggili, sfoglia i turni, R per rivederli
T                 chat con gli altri giocatori (partite online)
P                 direttiva di produzione: aria, terra, mare, sbarchi, difesa...
g                 vai a... (sposta il cursore, Invio per confermare)
v                 sveglia le unità sotto il cursore (anche il carico)
l / u             carica / scarica un trasporto o portaerei in città
p                 produzione della città sotto il cursore
D                 congeda l'unità attiva
m                 mappa del mondo (panoramica)
r                 centra la vista sul cursore
M                 audio: scegli musica ed effetti
N                 ☢ attacco nucleare sulla casella del cursore
C                 ☣ attacco chimico (entro 4 caselle dalle tue forze)
E                 fine turno
S / Q             salva / esci          ? questo aiuto

Attaccare: muovi un'unità su una casella nemica. Solo fanteria e corazzati
conquistano le città. Le navi entrano solo nei porti amici; gli aerei
consumano carburante e si riforniscono in città o sulle portaerei.
Ogni arma di distruzione di massa avvicina l'Orologio dell'Apocalisse
alla mezzanotte: a 0 minuti la guerra nucleare totale distrugge tutti."""


class UI:
    def __init__(self, scr, session, audio: Audio | None = None):
        self.scr = scr
        self.session = session
        self.audio = audio or Audio(mode="off")
        self.last_seq = max((e.seq for e in session.game.events), default=0)
        self.w = session.game.world
        self.viewer = session.faction if session.online else self._first_human()
        self.cursor = self._home_cell()
        self.view_x = 0
        self.view_y = 0
        self.reveal: set[int] = set()     # newsreel: cells the player may peek at
        self.phantom: dict[int, tuple[str, int]] = {}  # newsreel: (glyph, owner)
        self.fx: dict[int, tuple[str, str, int]] = {}  # newsreel effects: (char, colour, attr)
        self.last_reel: list[dict] = []
        self.bulletins: list[tuple[str, list[str], list[dict]]] = []  # archive: title, text, reel
        self.ticker: list[str] | None = None   # the bulletin's running chronicle
        self.active_id: int | None = None
        self.turn_key: tuple[int, int] | None = None
        self.over_shown = False
        self.skipped: set[int] = set()
        self._pan: tuple[int, int] | None = None     # mouse drag origin (screen)
        self._pan_view: tuple[int, int] | None = None  # view at drag start
        self.mode = "normal"          # normal | goto | nuke | chem | overview
        self.status = ""
        self.quit = False
        self._pairs: dict[tuple[int, int], int] = {}
        self._init_colors()
        self.territory_source = self._territory_sources()
        curses.curs_set(0)
        self.scr.keypad(True)
        # Motion reports are needed to drag the map while the button is held.
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.mouseinterval(0)

    @property
    def g(self):
        return self.session.game

    @property
    def active(self) -> Unit | None:
        if self.active_id is None:
            return None
        u = self.g.units.get(self.active_id)
        return u if u is not None and u.owner == self.viewer else None

    @active.setter
    def active(self, u: Unit | None) -> None:
        self.active_id = u.id if u is not None else None

    def my_turn(self) -> bool:
        g = self.g
        return not g.over and g.current == self.viewer and getattr(self.session, "started", True)

    # ----------------------------------------------------------- colours
    def _init_colors(self) -> None:
        self.has_color = curses.has_colors()
        if self.has_color:
            curses.start_color()
            try:
                curses.use_default_colors()
                self.default_bg = -1
            except curses.error:
                self.default_bg = curses.COLOR_BLACK
        self.palette = COLORS_256 if self.has_color and curses.COLORS >= 256 else COLORS_8
        self.rich = self.palette is COLORS_256

    def color(self, fg: str, bg: str | None = None) -> int:
        if not self.has_color:
            return 0
        f = self.palette.get(fg, self.palette["white"])
        b = self.palette.get(bg, self.default_bg) if bg else self.default_bg
        key = (f, b)
        if key not in self._pairs:
            n = len(self._pairs) + 1
            if n >= curses.COLOR_PAIRS:
                return 0
            curses.init_pair(n, f, b)
            self._pairs[key] = n
        return curses.color_pair(self._pairs[key])

    def owner_color(self, owner: int | None) -> str:
        return "neutral" if owner is None else self.g.factions[owner].color

    # ----------------------------------------------------------- helpers
    def _first_human(self) -> int:
        for f in self.g.factions:
            if f.human and f.alive:
                return f.idx
        return 0

    def _home_cell(self) -> int:
        cities = self.g.cities_of(self.viewer)
        if not cities:
            return self.w.idx(180, 20)
        fd = self.g.scenario.factions[self.viewer]
        first = fd.countries[0] if fd.countries else None
        return max(cities, key=lambda c: (c.iso == first, c.capital, c.size)).cell

    def _territory_sources(self) -> list[int]:
        """Which city each land cell belongs to (nearest over land)."""
        src = [-1] * self.w.size
        queue = deque()
        for c in self.g.cities:
            src[c.cell] = c.id
            queue.append(c.cell)
        land = self.w.land
        while queue:
            cur = queue.popleft()
            for n in self.w.neighbors[cur]:
                if land[n] and src[n] < 0:
                    src[n] = src[cur]
                    queue.append(n)
        return src

    def map_size(self) -> tuple[int, int]:
        h, w = self.scr.getmaxyx()
        return max(10, w - SIDEBAR - 1), max(5, h - LOG_ROWS - 2)

    def follow_cursor(self) -> None:
        mw, mh = self.map_size()
        cx, cy = self.w.xy(self.cursor)
        rel = (cx - self.view_x) % self.w.width
        if rel < 3 or rel > mw - 4:
            self.view_x = (cx - mw // 2) % self.w.width
        if cy < self.view_y + 2 or cy > self.view_y + mh - 3:
            self.view_y = cy - mh // 2
        self.view_y = max(0, min(self.view_y, max(0, self.w.height - mh)))

    def center(self) -> None:
        mw, mh = self.map_size()
        cx, cy = self.w.xy(self.cursor)
        self.view_x = (cx - mw // 2) % self.w.width
        self.view_y = max(0, min(cy - mh // 2, max(0, self.w.height - mh)))

    def date_text(self) -> str:
        start = START_DATES.get(self.g.scenario.key)
        if start is None:
            return f"Anno {1 + (self.g.turn - 1) // 52}, sett. {1 + (self.g.turn - 1) % 52}"
        d = start + dt.timedelta(weeks=self.g.turn - 1)
        months = "gen feb mar apr mag giu lug ago set ott nov dic".split()
        return f"{d.day} {months[d.month - 1]} {d.year}"

    def put(self, y: int, x: int, text: str, attr: int = 0) -> None:
        h, w = self.scr.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        text = text[: max(0, w - x - (1 if y == h - 1 else 0))]
        try:
            self.scr.addstr(y, x, text, attr)
        except curses.error:
            pass

    # ----------------------------------------------------------- drawing
    # ----------------------------------------------------------- sound
    def sounds(self) -> None:
        """Play the most important effect among the events this player has
        just learned about, and pick the music for the moment."""
        g = self.g
        fresh = [e for e in g.events if e.seq > self.last_seq
                 and (e.audience is None or self.viewer in e.audience)]
        if g.events:
            self.last_seq = max(self.last_seq, max(e.seq for e in g.events))
        name = pick_sound(g, self.viewer, fresh)
        if name:
            self.audio.sfx(name)
        self.audio.music(self.music_for())

    def music_for(self) -> str:
        g = self.g
        if self.session.online and not self.session.started:
            return "menu"
        if g.over:
            winner, reason = g.over
            if reason == "armageddon":
                return "midnight"
            return "victory" if winner == self.viewer or (
                not self.session.online and g.factions[winner].human) else "defeat"
        return "tension" if g.doomsday <= 5 else "war"

    def draw(self) -> None:
        self.sounds()
        self.scr.erase()
        if self.mode == "overview":
            self.draw_overview()
        else:
            self.draw_map()
        self.draw_top()
        self.draw_sidebar()
        self.draw_log()
        self.draw_status()
        self.scr.refresh()

    def cell_glyph(self, cell: int, vis: set[int], path: set[int]) -> tuple[str, int]:
        g = self.g
        land = self.w.land[cell]
        seen = cell in vis
        bg = None if land or not self.rich else "sea"
        dim = 0 if seen else curses.A_DIM
        city = g.city(cell)
        units = [u for u in g.units_at(cell)
                 if (seen or cell in self.reveal) and (g.sees(self.viewer, u) or cell in self.reveal)] \
            if cell in g.at else []
        if cell in self.fx:
            ch, color, extra = self.fx[cell]
            return ch, self.color(color, bg) | curses.A_BOLD | extra
        if cell in self.phantom:
            kind, owner = self.phantom[cell]
            return kind, self.color(self.owner_color(owner), bg) | curses.A_BOLD
        if self.active is not None and self.active.cell == cell and self.active.id in g.units:
            return self.active.kind, self.color(self.owner_color(self.active.owner), bg) | curses.A_BOLD | curses.A_REVERSE
        if city is not None:
            glyph = "★" if city.capital else "◉" if city.size == 3 else "●" if city.size == 2 else "•"
            attr = self.color(self.owner_color(city.owner) if city.owner is not None else "white", bg) | curses.A_BOLD
            if any(u.owner == self.viewer for u in g.units_at(cell)):
                attr |= curses.A_UNDERLINE
            return glyph, attr
        if units:
            u = units[0]
            return u.kind, self.color(self.owner_color(u.owner), bg) | curses.A_BOLD
        if cell in path:
            return "·", self.color("white", bg) | curses.A_BOLD
        if cell in g.fallout:
            return "☢", self.color("fallout", bg) | dim
        dots = self.w.dots[cell]
        if land:
            src = self.territory_source[cell]
            owner = g.cities[src].owner if src >= 0 else None
            return chr(0x2800 + (dots or 0xFF)), self.color(self.owner_color(owner)) | dim
        if dots:
            return chr(0x2800 + dots), self.color("coast", bg) | dim
        return " ", self.color("white", bg)

    def draw_map(self) -> None:
        g = self.g
        mw, mh = self.map_size()
        vis = g.visible(self.viewer) | self.reveal
        path: set[int] = set()
        if self.mode == "goto" and self.active is not None and self.active.id in g.units:
            route = g.path(self.active, self.cursor) or []
            path = set(route[:-1])
        for sy in range(mh):
            y = self.view_y + sy
            if y >= self.w.height:
                break
            for sx in range(mw):
                cell = y * self.w.width + (self.view_x + sx) % self.w.width
                ch, attr = self.cell_glyph(cell, vis, path)
                if cell == self.cursor:
                    attr = (attr | curses.A_REVERSE) if self.mode == "normal" else (
                        self.color("alert") | curses.A_REVERSE | curses.A_BOLD)
                    if self.mode in ("nuke", "chem"):
                        ch = "✕"
                elif self.mode in ("nuke", "chem") and self.w.dist(cell, self.cursor) == 1:
                    attr |= curses.A_REVERSE
                self.put(1 + sy, sx, ch, attr)

    def draw_overview(self) -> None:
        """The whole world in the map area; each Braille dot is one cell."""
        g = self.g
        mw, mh = self.map_size()
        kx = max(1, -(-self.w.width // (mw * 2)))
        ky = max(1, -(-self.w.height // (mh * 4)))
        bits = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]
        cols = -(-self.w.width // (2 * kx))
        rows = -(-self.w.height // (4 * ky))
        self.overview_geom = (kx, ky, cols, rows)
        for sy in range(min(rows, mh)):
            for sx in range(min(cols, mw)):
                b = 0
                owners: Counter = Counter()
                city_here = None
                for j in range(4):
                    for i in range(2):
                        x0, y0 = (sx * 2 + i) * kx, (sy * 4 + j) * ky
                        land = False
                        for yy in range(y0, min(y0 + ky, self.w.height)):
                            for xx in range(x0, min(x0 + kx, self.w.width)):
                                c = yy * self.w.width + xx
                                if self.w.land[c]:
                                    land = True
                                    src = self.territory_source[c]
                                    owners[g.cities[src].owner if src >= 0 else None] += 1
                                cid = g.city_at.get(c)
                                if cid is not None and (city_here is None or g.cities[cid].owner is not None):
                                    city_here = g.cities[cid]
                        if land:
                            b |= bits[j][i]
                owner = owners.most_common(1)[0][0] if owners else None
                if city_here is not None and city_here.owner is not None and city_here.owner != owner:
                    owner = city_here.owner
                attr = self.color(self.owner_color(owner) if b else "coast", None if b or not self.rich else "sea")
                ch = chr(0x2800 + b) if b else " "
                cx, cy = self.w.xy(self.cursor)
                if cx // (2 * kx) == sx and cy // (4 * ky) == sy:
                    attr |= curses.A_REVERSE
                self.put(1 + sy, sx, ch, attr)
        self.put(1 + min(rows, mh), 0, "Panoramica: clic o frecce per scegliere, Invio/m per tornare",
                 self.color("dim"))

    def draw_top(self) -> None:
        g = self.g
        h, w = self.scr.getmaxyx()
        self.put(0, 0, " " * (w - 1), curses.A_REVERSE)
        title = f" THE EMPIRE · {g.scenario.name} · {self.date_text()} · turno {g.turn} "
        self.put(0, 0, title, curses.A_REVERSE | curses.A_BOLD)
        minutes = max(0, g.doomsday)
        clock = f" ☢ 23:{60 - minutes:02d}  {minutes} MIN A MEZZANOTTE  DEFCON {defcon(minutes)} "
        level = "alert" if minutes <= 3 else "fallout" if minutes <= 6 else "good"
        self.put(0, max(len(title) + 1, w - len(clock) - 1), clock, self.color(level) | curses.A_REVERSE | curses.A_BOLD)
        if g.current != self.viewer and not g.over:
            self.put(0, len(title), f" ⌛ tocca a {g.faction.name} ", curses.A_REVERSE)
        left = self.session.seconds_left()
        if left is not None and not g.over:
            self.put(0, max(len(title) + 1, w - len(clock) - 12), f" ⏱ {left // 60}:{left % 60:02d} ",
                     self.color("alert" if left < 30 else "panel") | curses.A_REVERSE | curses.A_BOLD)

    def draw_sidebar(self) -> None:
        g = self.g
        h, w = self.scr.getmaxyx()
        x = w - SIDEBAR
        for y in range(1, h - 1):
            self.put(y, x - 1, "│", self.color("dim"))
        fac = g.factions[self.viewer]
        row = 1
        self.put(row, x, fac.name.upper()[:SIDEBAR - 1], self.color(fac.color) | curses.A_BOLD)
        row += 1
        cities = g.cities_of(self.viewer)
        industry = sum(g.production_rate(c) for c in cities)
        units = g.units_of(self.viewer)
        self.put(row, x, f"Città {len(cities):3d}  industria {industry:5.1f}/turno")
        row += 1
        self.put(row, x, f"Unità {len(units):3d}/{g.supply_limit(self.viewer)}  ☢ {fac.warheads:2d}  ☣ {fac.chemicals}")
        row += 1
        if fac.directive:
            label = DIRECTIVES[fac.directive].split(" (")[0]
            self.put(row, x, f"Direttiva: {label} (P)"[:SIDEBAR - 1], self.color("dim"))
            row += 1
        others = [f for f in g.factions if f.idx != self.viewer]
        names = self.session.player_names()
        for f in others:
            state = f"{len(g.cities_of(f.idx)):3d} città" if f.alive else "  sconfitto"
            mark = "≈" if g.truce_left(self.viewer, f.idx) else " "
            self.put(row, x, f"{f.name[:21]:21s}{mark}{state}", self.color(f.color))
            row += 1
            if f.idx in names:
                self.put(row, x, f"  giocatore: {names[f.idx]}"[:SIDEBAR - 1], self.color("dim"))
                row += 1
        self.put(row, x, f"{'Neutrali':22s}{len(g.cities_of(None)):3d} città", self.color("neutral"))
        row += 1
        self.put(row, x, "─" * (SIDEBAR - 1), self.color("dim"))
        row += 1
        waiting = len(self.needing_orders())
        self.put(row, x, f"In attesa di ordini: {waiting}", curses.A_BOLD if waiting else self.color("dim"))
        row += 1
        a = self.active
        if a is not None and a.id in g.units:
            row = self._unit_lines(a, row, x, active=True)
            odds = g.odds(a, self.cursor) if self.cursor in self.w.neighbors[a.cell] else None
            if odds is not None:
                self.put(row, x, f"⚔ Probabilità di vittoria: {odds * 100:3.0f}%",
                         self.color("good" if odds >= 0.6 else "fallout" if odds >= 0.35 else "alert") | curses.A_BOLD)
                row += 1
        self.put(row, x, "─" * (SIDEBAR - 1), self.color("dim"))
        row += 1
        row = self._cell_lines(self.cursor, row, x, h - 2)

    def _unit_lines(self, u: Unit, row: int, x: int, active: bool = False) -> int:
        g = self.g
        t = u.type
        mine = u.owner == self.viewer
        label = ("▶ " if active else "  ") + t.name
        if not mine:
            label += f" ({g.factions[u.owner].name})"
        self.put(row, x, label[:SIDEBAR - 1], self.color(self.owner_color(u.owner)) | (curses.A_BOLD if active else 0))
        row += 1
        if mine:
            info = f"    PV {u.hp}/{t.hp}  mosse {u.moves}/{t.move}"
            if t.domain == "air":
                info += f"  carb. {u.fuel}"
            self.put(row, x, info)
            row += 1
            extra = {"sentry": "sentinella", "fortify": "fortificata", "goto": "in marcia",
                     "auto": "automatica"}.get(u.order or "", "")
            if u.cargo:
                kinds = Counter(g.units[c].kind for c in u.cargo if c in g.units)
                extra += f" carico {len(u.cargo)}/{t.capacity}: " + " ".join(f"{n}{k}" for k, n in kinds.items())
            if extra:
                self.put(row, x, "    " + extra.strip(), self.color("dim"))
                row += 1
        return row

    def _cell_lines(self, cell: int, row: int, x: int, bottom: int) -> int:
        g = self.g
        lon, lat = self.w.lonlat(cell)
        country = self.w.country_of(cell)
        terrain = "terra" if self.w.land[cell] else "mare"
        where = f"{abs(lat):.0f}°{'N' if lat >= 0 else 'S'} {abs(lon):.0f}°{'E' if lon >= 0 else 'W'}"
        self.put(row, x, f"{where} · {terrain}" + (f" · {country['name']}" if country else ""))
        row += 1
        if cell in g.fallout:
            self.put(row, x, f"☢ ricaduta radioattiva ({g.fallout[cell]} turni)", self.color("fallout"))
            row += 1
        city = g.city(cell)
        if city is not None:
            tag = " ★ capitale" if city.capital else ""
            self.put(row, x, f"{city.name}{tag}"[:SIDEBAR - 1], self.color(self.owner_color(city.owner)) | curses.A_BOLD)
            row += 1
            self.put(row, x, f"  {g.faction_name(city.owner)} · dimensione {city.size} · milizia {city.militia}")
            row += 1
            if city.owner == self.viewer:
                cost = production_cost(city.production)
                rate = g.production_rate(city)
                eta = "∞" if rate <= 0 else str(max(0, -(-(cost - city.progress) // rate)))
                hand = " (a mano)" if city.manual and g.factions[self.viewer].directive else ""
                self.put(row, x, f"  Produce: {PRODUCTION_NAMES[city.production]}{hand}"[:SIDEBAR - 1])
                row += 1
                self.put(row, x, f"  {city.progress:.0f}/{cost} punti, pronto in {eta} turni")
                row += 1
                notes = []
                if city.irradiated:
                    notes.append(f"irradiata {city.irradiated}t")
                if city.unrest:
                    notes.append(f"disordini {city.unrest}t")
                if notes:
                    self.put(row, x, "  " + ", ".join(notes), self.color("alert"))
                    row += 1
        units = [u for u in g.units_at(cell) if g.sees(self.viewer, u)]
        if city is not None and units and len(units) > 4:
            kinds = Counter((u.owner, u.kind) for u in units)
            text = "  Guarnigione: " + " ".join(f"{n}{k}" for (_, k), n in kinds.items())
            self.put(row, x, text[:SIDEBAR - 1])
            row += 1
            return row
        for u in units:
            if row >= bottom - 1:
                break
            row = self._unit_lines(u, row, x, active=u is self.active)
        return row

    def draw_log(self) -> None:
        h, w = self.scr.getmaxyx()
        mw = w - SIDEBAR - 1
        top = h - LOG_ROWS - 1
        self.put(top, 0, "─" * mw, self.color("dim"))
        if self.ticker is not None:   # the bulletin's chronicle, line by line
            self.put(top, 2, " BOLLETTINO DI GUERRA ", self.color("alert") | curses.A_REVERSE | curses.A_BOLD)
            for k, line in enumerate(self.ticker[-(LOG_ROWS - 1):]):
                attr = curses.A_BOLD if "NOI" in line or "PERSA" in line or "☢" in line else 0
                self.put(top + 1 + k, 0, f" {line}"[:mw].ljust(mw), self.color("panel") | attr)
            return
        events = [e for e in self.g.events if e.audience is None or self.viewer in e.audience]
        colors = {"info": "panel", "combat": "orange", "alert": "alert", "wmd": "wmd", "chat": "cyan"}
        for k, e in enumerate(events[-(LOG_ROWS - 1):]):
            self.put(top + 1 + k, 0, f"[{e.turn:3d}] {e.text}"[:mw].ljust(mw),
                     self.color(colors.get(e.level, "panel")) | (curses.A_BOLD if e.level in ("wmd", "alert") else 0))

    def draw_status(self) -> None:
        h, w = self.scr.getmaxyx()
        hint = {
            "normal": "qweadzxc muovi · frecce cursore · n prossima · g vai · p produzione · E fine turno · ? aiuto",
            "goto": "VAI A: sposta il cursore e premi Invio (Esc annulla)",
            "nuke": "☢ BERSAGLIO NUCLEARE: sposta il cursore e premi Invio (Esc annulla)",
            "chem": "☣ BERSAGLIO CHIMICO: sposta il cursore e premi Invio (Esc annulla)",
            "overview": "PANORAMICA",
        }[self.mode]
        text = self.status or hint
        self.put(h - 1, 0, text[: w - 1], curses.A_BOLD if self.status else self.color("dim"))

    # ----------------------------------------------------------- dialogs
    def dialog(self, title: str, lines: list[str], footer: str = "premi un tasto") -> int:
        h, w = self.scr.getmaxyx()
        width = min(w - 4, max(len(title) + 4, len(footer) + 4, *(len(l) + 4 for l in lines)))
        height = min(h - 2, len(lines) + 4)
        y0, x0 = (h - height) // 2, (w - width) // 2
        win = curses.newwin(height, width, y0, x0)
        win.keypad(True)
        win.erase()
        win.box()
        try:
            win.addstr(0, 2, f" {title} "[: width - 4], curses.A_BOLD)
            for k, line in enumerate(lines[: height - 4]):
                win.addstr(2 + k, 2, line[: width - 4])
            win.addstr(height - 1, 2, f" {footer} "[: width - 4], curses.A_DIM)
        except curses.error:
            pass
        win.refresh()
        key = win.getch()
        del win
        self.scr.touchwin()
        return key

    def ask(self, title: str, lines: list[str], prompt: str, length: int = 8) -> str:
        """A dialog with a one-line text field under its message."""
        h, w = self.scr.getmaxyx()
        width = min(w - 4, max(len(title) + 4, len(prompt) + length + 6, *(len(l) + 4 for l in lines)))
        height = min(h - 2, len(lines) + 6)
        win = curses.newwin(height, width, (h - height) // 2, (w - width) // 2)
        win.erase()
        win.box()
        try:
            win.addstr(0, 2, f" {title} "[: width - 4], curses.A_BOLD)
            for k, line in enumerate(lines[: height - 6]):
                win.addstr(2 + k, 2, line[: width - 4])
            win.addstr(height - 3, 2, prompt[: width - 4], curses.A_BOLD)
        except curses.error:
            pass
        curses.echo()
        curses.curs_set(1)
        try:
            text = win.getstr(height - 3, 3 + len(prompt), length).decode("utf-8", "ignore")
        except curses.error:
            text = ""
        curses.noecho()
        curses.curs_set(0)
        del win
        self.scr.touchwin()
        return text.strip()

    def production_menu(self, city) -> None:
        g = self.g
        keys = [k for k in list(UNIT_TYPES) + [WARHEAD, CHEMICAL] if g.can_build(city, k)]
        rate = g.production_rate(city)
        lines = []
        for k in keys:
            cost = production_cost(k)
            eta = "∞" if rate <= 0 else f"{-(-cost // rate):.0f}"
            mark = "▶" if k == city.production else " "
            if k in UNIT_TYPES:
                t = UNIT_TYPES[k]
                stats = f"att {t.attack} dif {t.defense} PV {t.hp} mosse {t.move}"
            else:
                stats = "scorta strategica"
            lines.append(f"{mark} {k}  {PRODUCTION_NAMES[k]:20s} costo {cost:3d}  {eta:>3s} turni  {stats}")
        directive = g.factions[self.viewer].directive
        if directive and city.manual:
            lines += ["", f"  X  torna alla direttiva: {DIRECTIVES[directive].split(' (')[0]}"]
        elif directive:
            lines += ["", "  Scegliendo a mano, questa città non seguirà più la direttiva."]
        key = self.dialog(f"Produzione di {city.name} ({rate:.1f} punti/turno)", lines,
                          "lettera per scegliere, Esc per annullare")
        if key < 0 or key > 255:
            return
        ch = chr(key).upper()
        if ch == "X" and directive and city.manual:
            self.do({"op": "release", "city": city.id})
            self.status = f"{city.name} torna a seguire la direttiva."
            return
        if ch in keys and self.do({"op": "produce", "city": city.id, "key": ch}) == "ok":
            self.status = f"{city.name} ora produce {PRODUCTION_NAMES[ch]}."

    DIRECTIVE_KEYS = {"0": "", "1": "auto", "2": "land", "3": "air", "4": "sea",
                      "5": "amphibious", "6": "defense", "7": "nuclear"}

    def directive_menu(self) -> None:
        """One order for every city: what the whole war economy builds."""
        fac = self.g.factions[self.viewer]
        lines = ["Una direttiva cambia subito la produzione di tutte le città", ""]
        for key, name in self.DIRECTIVE_KEYS.items():
            mark = "▶" if fac.directive == name else " "
            lines.append(f"{mark} {key}  {DIRECTIVES[name]}")
        manual = sum(1 for c in self.g.cities_of(self.viewer) if c.manual)
        lines += ["", "Le città che hai impostato a mano restano come sono."]
        if manual:
            lines.append(f"Città scelte a mano: {manual}. Premi T per includere anche quelle.")
        key = self.dialog("Direttiva di produzione", lines, "numero, T per tutte, Esc")
        if key < 0 or key > 255:
            return
        ch = chr(key)
        include_all = False
        if ch in ("T", "t") and manual:
            include_all = True
            key = self.dialog("Direttiva per tutte le città", lines[2:2 + len(self.DIRECTIVE_KEYS)],
                              "numero, Esc")
            if key < 0 or key > 255:
                return
            ch = chr(key)
        if ch not in self.DIRECTIVE_KEYS:
            return
        name = self.DIRECTIVE_KEYS[ch]
        changed = self.do({"op": "directive", "name": name, "all": include_all})
        label = DIRECTIVES[name].split(" (")[0]
        self.status = f"Direttiva: {label}. Città riconvertite: {changed}." if name else \
            "Produzione manuale: ogni città continua con quello che sta costruendo."

    def diplomacy_menu(self) -> None:
        g = self.g
        others = [f for f in g.factions if f.idx != self.viewer and f.alive]
        offers = g.proposals_to(self.viewer)
        lines = []
        for k, f in enumerate(others, 1):
            left = g.truce_left(self.viewer, f.idx)
            if left:
                state = f"tregua ({left} turni)"
            elif f.idx in offers:
                state = "TI PROPONE UNA TREGUA"
            elif [self.viewer, f.idx] in g.proposals:
                state = "proposta inviata"
            else:
                state = "in guerra"
            lines.append(f"{k}  {f.name:24s} {state}")
        lines += ["", "Numero: proponi una tregua o rispondi a una proposta.",
                  "Durante la tregua le due fazioni non possono attaccarsi."]
        key = self.dialog("Diplomazia", lines, "numero o Esc")
        if not ord("1") <= key < ord("1") + len(others):
            return
        f = others[key - ord("1")]
        if f.idx in offers:
            answer = self.dialog("Tregua", [f"{f.name} propone una tregua.", "Accetti?"], "s / n")
            result = self.do({"op": "truce_answer", "target": f.idx,
                              "accept": answer in (ord("s"), ord("S"))})
        elif not g.truce_left(self.viewer, f.idx):
            result = self.do({"op": "truce", "target": f.idx})
        else:
            return
        self.status = describe(result) or self.status

    def music_menu(self) -> None:
        """Choose the background music and mute or unmute the effects."""
        a = self.audio
        lines = ["Musica", ""]
        for key, choice in MUSIC_KEYS.items():
            mark = "▶" if a.music_choice == choice else " "
            lines.append(f"{mark} {key}  {MUSIC_NAMES[choice]}")
        lines += ["", "Effetti", ""]
        mark = "▶" if a.effects else " "
        lines.append(f"{mark} e  effetti sonori: {'attivi' if a.effects else 'muti'}")
        key = self.dialog("Audio", lines, "lettera per scegliere, Esc per chiudere")
        if key < 0 or key > 255:
            return
        ch = chr(key).lower()
        if ch in MUSIC_KEYS:
            choice = MUSIC_KEYS[ch]
            a.select_music(choice)
            note = "" if a.available else " (nessun lettore audio trovato: solo il beep)"
            self.status = f"Musica: {MUSIC_NAMES[choice]}{note}."
        elif ch == "e":
            on = a.toggle_effects()
            self.status = f"Effetti sonori: {'attivi' if on else 'muti'}."

    def chat(self) -> None:
        text = self.ask("Messaggio", ["Scrivi un messaggio per tutti i giocatori."], "> ", 120)
        if text:
            self.do({"op": "chat", "text": text})

    # ----------------------------------------------------------- orders
    def do(self, cmd: dict) -> str:
        """Send one command through the session (local game or server)."""
        result = self.session.do(self.viewer, cmd, progress=self._progress)
        if result == "disconnected":
            self.status = "Connessione con il server perduta."
        self.sync()
        return result

    def _progress(self, who: str) -> None:
        self.status = f"⌛ {who} sta muovendo..."
        self.draw()

    def sync(self) -> None:
        """React to a new game state: a new turn, or the end of the game."""
        g = self.g
        if g.over:
            if not self.over_shown:
                self.over_shown = True
                self.game_over()
            return
        key = (g.turn, g.current)
        if key == self.turn_key:
            return
        self.turn_key = key
        if not self.session.online and g.faction.human:
            self.viewer = g.current
        if self.my_turn():
            self.start_human_turn()
        else:
            self.active = None
            if self.session.started:
                self.status = f"⌛ Tocca a {g.faction.name}: aspetta il tuo turno."

    def needing_orders(self) -> list[Unit]:
        g = self.g
        out = []
        for u in g.units.values():
            if u.owner != self.viewer or u.moves <= 0 or u.order is not None or u.id in self.skipped:
                continue
            if u.carrier is not None and u.type.domain == "land" and not any(
                    self.w.land[n] for n in self.w.neighbors[u.cell]):
                continue
            out.append(u)
        out.sort(key=lambda u: (self.w.dist(u.cell, self.cursor), u.id))
        return out

    def select_next(self) -> None:
        if not self.my_turn():
            return
        pending = self.needing_orders()
        if self.active is not None:
            pending = [u for u in pending if u.id != self.active_id] or pending
        if pending:
            self.select(pending[0])
        else:
            self.active = None
            self.status = "Tutte le unità hanno ricevuto ordini. Premi E per finire il turno."

    def select(self, u: Unit) -> None:
        self.active = u
        self.cursor = u.cell
        self.follow_cursor()

    def after_action(self) -> None:
        a = self.active
        if a is None or a.moves <= 0 or a.order is not None:
            self.select_next()
        else:
            self.cursor = a.cell
            self.follow_cursor()

    def move_active(self, dx: int, dy: int) -> None:
        a = self.active
        if a is None:
            self.status = "Nessuna unità selezionata (n per la prossima)."
            return
        target = self.w.step_dir(a.cell, dx, dy)
        if target is None:
            return
        kind = a.kind
        result = self.do({"op": "move", "unit": a.id, "cell": target})
        self.status = describe(result)
        self._unit_sound(kind, result)
        self.after_action()

    def _unit_sound(self, kind: str, result: str) -> None:
        """Our own unit's voice: its engine or boots when it moves, its guns
        when it fights (the outcome of the fight follows in the events)."""
        g = self.g
        if result == "moved":
            self.audio.sfx(f"move_{kind}")
        elif result in ("won", "lost", "captured"):
            self.audio.sfx(f"fire_{kind}", force=True)
            if result == "captured":
                self.audio.sfx("capture")
            elif result == "lost":
                self.audio.sfx("loss")
            if g.events:  # already heard: don't ring them again
                self.last_seq = max(self.last_seq, max(e.seq for e in g.events))

    def order(self, order: str | None, **extra) -> str:
        a = self.active
        if a is None:
            return "illegal"
        result = self.do({"op": "order", "unit": a.id, "order": order, **extra})
        self.after_action()
        return result

    def start_human_turn(self) -> None:
        g = self.g
        self.skipped.clear()
        self.active = None
        if not self.session.online and sum(1 for f in g.factions if f.human and f.alive) > 1:
            self.scr.erase()
            self.scr.refresh()
            self.dialog("Passaggio di consegne", [f"Tocca a: {g.faction.name}",
                                                  "Gli altri giocatori distolgano lo sguardo."])
        reel = self.session.take_reel(self.viewer) if hasattr(self.session, "take_reel") else []
        if reel:
            self.last_reel = reel
            title = f"BOLLETTINO DI GUERRA · {self.date_text()} · turno {g.turn}"
            self.bulletins.append((title, self.bulletin_text(reel), reel))
            del self.bulletins[:-30]
            self.play_bulletin(reel)
        self.select_next()
        if self.active is None:
            self.cursor = self._home_cell()
            self.center()
        self.status = f"Turno {g.turn}: ai tuoi ordini."
        self.warned = False
        if hasattr(self.session, "start_clock"):
            self.session.start_clock()
        if self.session.online:
            self.audio.sfx("turn")

    def end_human_turn(self) -> None:
        self.active = None
        g = self.g
        if g.events:  # the newsreel will ring every event; quiet the summary
            self.last_seq = max(self.last_seq, max(e.seq for e in g.events))
        self.do({"op": "end_turn"})

    # ------------------------------------------------------- newsreel
    def _focus(self, cell: int) -> None:
        """Pan the map so ``cell`` is in view (keep the view if it already is)."""
        mw, mh = self.map_size()
        cx, cy = self.w.xy(cell)
        rel = (cx - self.view_x) % self.w.width
        if rel < 3 or rel > mw - 4:
            self.view_x = (cx - mw // 2) % self.w.width
        if cy < self.view_y + 2 or cy > self.view_y + mh - 3:
            self.view_y = cy - mh // 2
        self.view_y = max(0, min(self.view_y, max(0, self.w.height - mh)))

    # Each frame of the bulletin: how long it stays on screen (seconds).
    REEL_PACE = {"walk": 0.015, "march": 0.04, "capture": 0.35, "fall": 0.5,
                 "nuke": 0.6, "chem": 0.4}

    def play_bulletin(self, reel: list[dict], then_read: bool = True) -> None:
        """The war bulletin, Theatre-Europe style: the camera follows what the
        others did since your last turn. Armies march as glowing marks, every
        attack gets its own close-up (the attacker flashes, fire, the
        explosion, the outcome), then a summary card. A key skips ahead."""
        g = self.g
        if g.events:  # the frames play the sounds; don't ring the events after
            self.last_seq = max(self.last_seq, max(e.seq for e in g.events))
        saved_status = self.status
        self.scr.nodelay(True)
        self.ticker = []
        last_unit = None
        try:
            for act in reel:
                if self._skip_key():
                    break
                op = act["op"]
                cell = act["cell"]
                self.reveal = {cell}
                self.fx = {}
                if op == "move":
                    self.phantom = {cell: (act["glyph"], act["owner"])}
                    new_unit = act.get("unit") != last_unit
                    last_unit = act.get("unit")
                    if new_unit:
                        self.audio.sfx(f"move_{act['glyph']}")
                    self.status = f"▶ Bollettino: {self._who(act)} in movimento"
                    self._focus(cell)
                    self.draw()
                    time.sleep(self.REEL_PACE["walk" if not new_unit else "march"])
                    continue
                last_unit = None
                self.phantom = {}
                line = self.scene_line(act)
                if line:
                    self.ticker.append(line)
                if op == "attack":
                    if self._attack_scene(act):
                        break
                    continue
                self._centre(cell)
                if op == "capture":
                    lost = act.get("old") == self.viewer
                    self.fx = {cell: ("⚑", self.owner_color(act.get("new")), curses.A_REVERSE)}
                    self.status = (f"▶ {self._faction(act.get('new'))} conquista {act.get('name', '')}"
                                   + (" — LA PERDIAMO!" if lost else ""))
                    if lost:
                        self.audio.sfx("loss", force=True)
                elif op == "fall":
                    self.status = f"▶ {self._faction(act.get('old'))} è caduta!"
                    self.audio.sfx("fall", force=True)
                elif op == "nuke":
                    self.fx = {c: ("☢", "fallout", curses.A_REVERSE) for c in self.w.ring(cell, 1)}
                    self.status = f"▶ ☢ Attacco nucleare su {act.get('name', '')}"
                    self.audio.sfx("nuke", force=True)
                elif op == "chem":
                    self.fx = {c: ("☣", "green", 0) for c in self.w.ring(cell, 1)}
                    self.status = f"▶ ☣ Armi chimiche su {act.get('name', '')}"
                    self.audio.sfx("gas", force=True)
                self.draw()
                time.sleep(self.REEL_PACE.get(op, 0.2))
        finally:
            self.scr.nodelay(False)
            self.reveal.clear()
            self.phantom.clear()
            self.fx.clear()
            self.ticker = None
            self.status = saved_status
            self.follow_cursor()
        if then_read and not g.over:
            self.draw()
            self.read_bulletins(len(self.bulletins) - 1 if self.bulletins else None)

    def _skip_key(self) -> bool:
        key = self.scr.getch()
        return 0 <= key <= 255 or key in (curses.KEY_ENTER,)

    def _faction(self, owner) -> str:
        return self.g.faction_name(owner)

    def _who(self, act: dict) -> str:
        kind = act.get("glyph", "")
        name = UNIT_TYPES[kind].name if kind in UNIT_TYPES else "unità"
        return f"{name} ({self._faction(act.get('owner'))})"

    def _centre(self, cell: int) -> None:
        mw, mh = self.map_size()
        cx, cy = self.w.xy(cell)
        self.view_x = (cx - mw // 2) % self.w.width
        self.view_y = max(0, min(cy - mh // 2, max(0, self.w.height - mh)))

    def _attack_scene(self, act: dict) -> bool:
        """Close-up of one attack. Returns True if the player skipped."""
        me = self.viewer
        target, frm = act["cell"], act.get("frm", act["cell"])
        on_us = act.get("defender") == me
        kind = act.get("glyph", "")
        colour = self.owner_color(act.get("attacker"))
        tgt = act.get("target") or ""
        tname = UNIT_TYPES[tgt].name.lower() if tgt in UNIT_TYPES else "la città"
        head = "⚔ ATTACCO CONTRO DI NOI" if on_us else "⚔ Scontro"
        self.status = f"{head}: {self._who(act)} attacca {tname} ({self._faction(act.get('defender'))})"
        self._centre(target)
        self.reveal = {target, frm}
        slow = 1.0 if on_us else 0.6
        # 1. the attacker comes into the light
        ring = [c for c in self.w.neighbors[target] if c != frm]
        for k in range(4):
            self.phantom = {frm: (kind, act.get("owner"))} if k % 2 == 0 else {}
            self.fx = {target: ("◎", "alert", curses.A_REVERSE)}
            if k % 2 == 0:   # a blinking ring draws the eye to the battle
                self.fx.update({c: ("·", "alert", curses.A_BOLD) for c in ring})
            self.draw()
            time.sleep(0.12 * slow)
            if self._skip_key():
                return True
        # 2. fire: the unit's own weapon, a flash travelling to the target
        self.phantom = {frm: (kind, act.get("owner"))}
        self.audio.sfx(f"fire_{kind}" if kind in UNIT_TYPES else "battle", force=on_us)
        for ch, col in (("✶", "fallout"), ("✸", "alert"), ("✹", "orange"), ("✸", "fallout"), ("✶", "alert")):
            self.fx = {target: (ch, col, curses.A_REVERSE)}
            self.draw()
            time.sleep(0.09 * slow)
        # 3. the outcome
        result = act.get("result")
        if result == "lost":
            self.phantom = {}
            self.fx = {frm: ("✕", colour, curses.A_REVERSE)}
            outcome = "l'attaccante è distrutto" + (" — la difesa tiene!" if on_us else "")
        elif result == "captured":
            self.fx = {target: ("⚑", colour, curses.A_REVERSE)}
            outcome = "la città cade"
        else:
            self.fx = {target: ("✕", "alert", curses.A_REVERSE)}
            outcome = "il bersaglio è distrutto" if tgt else "le difese della città crollano"
            if on_us:
                self.audio.sfx("loss")
        self.status += f" → {outcome}"
        self.draw()
        time.sleep(0.45 * slow)
        return self._skip_key()

    # ------------------------------------------------- written bulletin
    def _place(self, cell: int) -> str:
        """'a Vilnius', 'presso Vilnius' or coordinates, for the chronicle."""
        g = self.g
        city = g.city(cell)
        if city is not None:
            return f"a {city.name}"
        near = min(g.cities, key=lambda c: self.w.dist(c.cell, cell))
        if self.w.dist(near.cell, cell) <= 4:
            return f"presso {near.name}"
        lon, lat = self.w.lonlat(cell)
        return f"a {abs(lat):.0f}°{'N' if lat >= 0 else 'S'} {abs(lon):.0f}°{'E' if lon >= 0 else 'W'}"

    def scene_line(self, act: dict) -> str:
        """One line of chronicle for a bulletin scene (moves have none)."""
        me = self.viewer
        op = act["op"]
        if op == "attack":
            kind = act.get("glyph", "")
            who = UNIT_TYPES[kind].name if kind in UNIT_TYPES else "Unità"
            tgt = act.get("target") or ""
            result = act.get("result")
            city = self.g.city(act["cell"])
            if tgt in UNIT_TYPES:
                where = f"su {UNIT_TYPES[tgt].name} {self._place(act['cell'])}"
            else:
                where = f"sulla città di {city.name}" if city else f"{self._place(act['cell'])}"
            if act.get("defender") == me:
                outcome = {"lost": "RESPINTO", "captured": "LA CITTÀ CADE"}.get(
                    result, "PERDIAMO l'unità" if tgt in UNIT_TYPES else "difese a terra")
                return (f"⚔ CONTRO DI NOI · {who} ({self._faction(act.get('attacker'))}) "
                        f"{where} → {outcome}")
            outcome = {"lost": "fallisce", "captured": "la città cade"}.get(result, "bersaglio distrutto")
            return (f"⚔ {who} ({self._faction(act.get('attacker'))}) {where} "
                    f"({self._faction(act.get('defender'))}) → {outcome}")
        if op == "capture":
            lost = " — PERSA" if act.get("old") == me else ""
            return (f"⚑ {act.get('name', '?')} conquistata da {self._faction(act.get('new'))} "
                    f"(prima: {self._faction(act.get('old'))}){lost}")
        if op == "fall":
            return f"✖ {self._faction(act.get('old'))} ha perso l'ultima città: è fuori dalla guerra"
        if op == "nuke":
            return f"☢ {self._faction(act.get('actor'))} colpisce {act.get('name', '?')} con un'arma nucleare"
        if op == "chem":
            return f"☣ {self._faction(act.get('actor'))} usa armi chimiche su {act.get('name', '?')}"
        return ""

    def bulletin_text(self, reel: list[dict]) -> list[str]:
        """The written bulletin: the front, the battles seen, the cities, the
        weapons of mass destruction and the movements observed."""
        me = self.viewer
        attacks = [a for a in reel if a["op"] == "attack"]
        on_us = [a for a in attacks if a.get("defender") == me]
        others = [a for a in attacks if a.get("defender") != me]
        cities = [a for a in reel if a["op"] in ("capture", "fall")]
        wmd = [a for a in reel if a["op"] in ("nuke", "chem")]
        moves: dict[int, dict] = {}
        for a in reel:
            if a["op"] == "move":
                moves[a["unit"]] = a          # last seen position of each unit
        out: list[str] = []
        if wmd:
            out += ["ARMI DI DISTRUZIONE DI MASSA"] + [self.scene_line(a) for a in wmd] + [""]
        if on_us:
            held = sum(1 for a in on_us if a.get("result") == "lost")
            out.append(f"IL NOSTRO FRONTE · {len(on_us)} attacchi subiti, {held} respinti")
            out += [self.scene_line(a) for a in on_us] + [""]
        if cities:
            lost = sum(1 for a in cities if a["op"] == "capture" and a.get("old") == me)
            out.append("CITTÀ CHE HANNO CAMBIATO BANDIERA" + (f" · ne perdiamo {lost}" if lost else ""))
            out += [self.scene_line(a) for a in cities] + [""]
        if others:
            out.append(f"ALTRI SCONTRI AVVISTATI · {len(others)}")
            out += [self.scene_line(a) for a in others] + [""]
        if moves:
            by_kind = Counter(UNIT_TYPES[a["glyph"]].name for a in moves.values() if a["glyph"] in UNIT_TYPES)
            by_side = Counter(self._faction(a["owner"]) for a in moves.values())
            out.append(f"MOVIMENTI OSSERVATI · {len(moves)} unità")
            out.append("  " + ", ".join(f"{n} {k.lower()}" for k, n in by_kind.most_common()))
            out.append("  " + ", ".join(f"{side}: {n}" for side, n in by_side.most_common()))
            near = Counter(self._place(a["cell"]) for a in moves.values()).most_common(3)
            out.append("  Zone più attive: " + ", ".join(f"{p.split(' ', 1)[1]} ({n})" for p, n in near))
        return out or ["Nessuna novità di rilievo sul fronte."]

    def read_bulletins(self, index: int | None) -> None:
        """Read the written bulletins: ←/→ older and newer turns, ↑/↓ scroll,
        R replays the animation, any other key closes."""
        if index is None or not self.bulletins:
            self.status = "Nessun bollettino ancora: arriverà a fine turno."
            return
        while True:
            title, lines, reel = self.bulletins[index]
            nav = f"{index + 1}/{len(self.bulletins)}"
            key = self.pager(f"{title} ({nav})", lines,
                             "↑↓ scorri · ←→ turni precedenti/successivi · R rivedi l'animazione · Esc chiudi")
            if key == curses.KEY_LEFT and index > 0:
                index -= 1
            elif key == curses.KEY_RIGHT and index < len(self.bulletins) - 1:
                index += 1
            elif key in (ord("r"), ord("R")):
                self.play_bulletin(reel, then_read=False)
            elif key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                continue
            else:
                return

    def pager(self, title: str, lines: list[str], footer: str) -> int:
        """A scrollable text window; returns the key that closed it."""
        h, w = self.scr.getmaxyx()
        width = min(w - 4, max(60, min(120, max((len(l) for l in lines), default=0) + 4)))
        height = min(h - 2, len(lines) + 4)
        body = height - 4
        win = curses.newwin(height, width, (h - height) // 2, (w - width) // 2)
        win.keypad(True)
        top = 0
        while True:
            win.erase()
            win.box()
            try:
                win.addstr(0, 2, f" {title} "[: width - 4], curses.A_BOLD)
                for k, line in enumerate(lines[top: top + body]):
                    attr = curses.A_BOLD if line.isupper() or "NOI" in line or "PERSA" in line else 0
                    win.addstr(2 + k, 2, line[: width - 4], attr)
                more = "▼" if top + body < len(lines) else " "
                win.addstr(height - 1, 2, f" {footer} {more} "[: width - 4], curses.A_DIM)
            except curses.error:
                pass
            win.refresh()
            key = win.getch()
            if key in (curses.KEY_DOWN, ord("j")) and top + body < len(lines):
                top += 1
            elif key in (curses.KEY_UP, ord("k")) and top > 0:
                top -= 1
            elif key == curses.KEY_NPAGE:
                top = min(max(0, len(lines) - body), top + body)
            elif key == curses.KEY_PPAGE:
                top = max(0, top - body)
            elif key in (curses.KEY_DOWN, curses.KEY_UP, -1):
                continue
            else:
                del win
                self.scr.touchwin()
                return key

    def game_over(self) -> None:
        g = self.g
        self.draw()
        winner, reason = g.over
        if reason == "armageddon":
            lines = ["Gli arsenali si sono svuotati in pochi minuti.",
                     "Le città del mondo sono in fiamme; l'inverno nucleare scende.",
                     "", "NESSUNO HA VINTO.", "",
                     "« Strano gioco. L'unica mossa vincente è non giocare. »"]
            title = "MEZZANOTTE"
        else:
            fac = g.factions[winner]
            if self.session.online:
                human_won = winner == self.viewer
            else:
                human_won = fac.human
            why = {"conquest": "ha sconfitto tutti i rivali",
                   "domination": "domina il mondo",
                   "turns": "vince ai punti allo scadere"}[reason]
            lines = [f"{fac.name} {why}.", "",
                     "VITTORIA!" if human_won else "SCONFITTA.", ""]
            for f in sorted(g.factions, key=g.score, reverse=True):
                lines.append(f"{f.name:24s} punti {g.score(f):5d}  città {len(g.cities_of(f.idx)):3d}  "
                             f"armi DM usate {f.used_wmd}")
            title = "FINE DELLA GUERRA"
        self.dialog(title, lines, "premi un tasto per uscire")
        self.quit = True

    # ----------------------------------------------------------- input
    VIEW_KEYS = {ord("m"), ord("M"), ord("r"), ord("?"), ord("Q"), ord("T"), ord("n"), ord("B"), 9}

    def handle(self, key: int) -> None:
        g = self.g
        self.status = ""
        if key == curses.KEY_RESIZE:
            self.follow_cursor()
            return
        if key == curses.KEY_MOUSE:
            self.mouse()
            return
        if self.mode == "overview":
            if key in CURSOR_KEYS:
                dx, dy = CURSOR_KEYS[key]
                kx, ky, _, _ = getattr(self, "overview_geom", (2, 2, 0, 0))
                self.move_cursor(dx * 2 * kx, dy * 4 * ky)
            elif key in (10, 13, 27, ord("m"), curses.KEY_ENTER):
                self.mode = "normal"
                self.center()
            return
        if self.mode in ("goto", "nuke", "chem"):
            if key in CURSOR_KEYS:
                self.move_cursor(*CURSOR_KEYS[key])
            elif key in DIRECTIONS:
                self.move_cursor(*DIRECTIONS[key])
            elif key == 27:
                self.mode = "normal"
                if self.active is not None:
                    self.cursor = self.active.cell
            elif key in (10, 13, curses.KEY_ENTER):
                self.confirm_target()
            return
        if key in CURSOR_KEYS:
            self.move_cursor(*CURSOR_KEYS[key])
            return
        if not self.my_turn() and key not in self.VIEW_KEYS and key != -1:
            if not self.session.started:
                self.status = "In attesa che arrivino tutti i giocatori..."
            elif not g.over:
                self.status = f"Attendi il tuo turno: ora tocca a {g.faction.name}."
            return
        if key in DIRECTIONS:
            self.move_active(*DIRECTIONS[key])
        elif key in (ord("n"), 9):
            self.select_next()
        elif key == ord(" "):
            if self.active is not None:
                self.skipped.add(self.active.id)
            self.select_next()
        elif key in (10, 13, curses.KEY_ENTER):
            self.select_at_cursor()
        elif key == ord("s") and self.active:
            self.order("sentry")
        elif key == ord("f") and self.active:
            if self.active.type.domain == "land":
                self.order("fortify")
            else:
                self.status = "Solo le unità di terra possono fortificarsi."
        elif key == ord("A") and self.active:
            self.order("auto")
            self.status = "Unità affidata all'IA (Invio sull'unità per riprenderla)."
        elif key == ord("P"):
            self.directive_menu()
        elif key == ord("g") and self.active:
            self.mode = "goto"
        elif key == ord("v"):
            woke = self.do({"op": "wake", "cell": self.cursor})
            self.status = f"{woke} unità sveglie."
            self.skipped.clear()
        elif key == ord("l") and self.active:
            n = self.do({"op": "load", "unit": self.active.id})
            self.status = f"Caricate {n} unità." if n not in ("0", "illegal") else "Niente da caricare (serve una nave in città)."
        elif key == ord("u") and self.active:
            n = self.do({"op": "unload", "unit": self.active.id})
            self.status = f"Scaricate {n} unità." if n not in ("0", "illegal") else "Si scarica solo in città."
        elif key == ord("p"):
            city = g.city(self.cursor)
            if city is not None and city.owner == self.viewer:
                self.production_menu(city)
            else:
                self.status = "Metti il cursore su una tua città."
        elif key == ord("D") and self.active:
            if self.dialog("Congedo", [f"Congedare {self.active.type.name}?"], "s per confermare") in (ord("s"), ord("S")):
                self.do({"op": "disband", "unit": self.active.id})
                self.active = None
                self.select_next()
        elif key == ord("O"):
            self.diplomacy_menu()
        elif key == ord("B"):
            self.read_bulletins(len(self.bulletins) - 1 if self.bulletins else None)
        elif key == ord("T"):
            if self.session.online:
                self.chat()
            else:
                self.status = "La chat serve nelle partite online."
        elif key == ord("m"):
            self.mode = "overview"
        elif key == ord("M"):
            self.music_menu()
        elif key == ord("r"):
            self.center()
        elif key == ord("N"):
            if g.factions[self.viewer].warheads <= 0:
                self.status = "Nessuna testata nucleare disponibile."
            else:
                self.mode = "nuke"
        elif key == ord("C"):
            if g.factions[self.viewer].chemicals <= 0:
                self.status = "Nessuna arma chimica disponibile."
            else:
                self.mode = "chem"
        elif key == ord("E"):
            self.end_human_turn()
        elif key == ord("S"):
            self.save()
        elif key == ord("Q"):
            note = "Il server tiene la partita: potrai rientrare." if self.session.online \
                else "La partita verrà salvata."
            if self.dialog("Uscire?", [note], "s per uscire") in (ord("s"), ord("S")):
                if not self.session.online:
                    self.save()
                self.quit = True
        elif key == ord("?"):
            self.dialog("Comandi", HELP.splitlines())

    def move_cursor(self, dx: int, dy: int) -> None:
        x, y = self.w.xy(self.cursor)
        y = max(0, min(self.w.height - 1, y + dy))
        self.cursor = self.w.idx(x + dx, y)
        self.follow_cursor()

    def select_at_cursor(self) -> None:
        g = self.g
        mine = [u for u in g.units_at(self.cursor) if u.owner == self.viewer]
        for u in list(mine):
            mine += [g.units[c] for c in u.cargo if c in g.units]
        if not mine:
            city = g.city(self.cursor)
            if city is not None and city.owner == self.viewer:
                self.production_menu(city)
            return
        ids = [u.id for u in mine]
        k = (ids.index(self.active_id) + 1) % len(ids) if self.active_id in ids else 0
        u = mine[k]
        self.skipped.discard(u.id)
        self.select(u)
        if u.order in ("sentry", "fortify", "auto"):
            self.do({"op": "order", "unit": u.id, "order": None})

    def confirm_target(self) -> None:
        g = self.g
        mode, self.mode = self.mode, "normal"
        if mode == "goto":
            a = self.active
            if a is not None:
                result = self.order("goto", target=self.cursor)
                if result != "ok":
                    self.status = describe(result)
                    if self.active is not None:
                        self.cursor = self.active.cell
            return
        city = g.city(self.cursor)
        place = city.name if city else "la casella selezionata"
        if mode == "chem":
            if not g.can_chemical(self.viewer, self.cursor):
                self.status = f"Bersaglio fuori portata (max {CHEM_RANGE} caselle dalle tue forze)."
                return
            if self.dialog("☣ Armi chimiche", [f"Colpire {place} con gas nervino?",
                                               "Orologio dell'Apocalisse: -1 minuto."],
                           "s per confermare") in (ord("s"), ord("S")):
                self.status = describe(self.do({"op": "chem", "cell": self.cursor}))
        else:
            if city is not None and city.owner == self.viewer:
                self.status = "Non puoi colpire una tua città."
                return
            code = f"{random.randint(0, 9999):04d}"
            lines = [f"Bersaglio: {place}",
                     f"Testate disponibili: {g.factions[self.viewer].warheads}",
                     f"Orologio dell'Apocalisse: {g.doomsday} minuti (-2/-3 dopo il lancio)",
                     "Il nemico potrebbe rispondere con tutto il suo arsenale.", "",
                     f"CODICE DI AUTORIZZAZIONE: {code}"]
            if self.ask("☢ AUTORIZZAZIONE AL LANCIO", lines, "Digita il codice (Invio):", 4) == code:
                self.status = describe(self.do({"op": "nuke", "cell": self.cursor}))
            else:
                self.status = "Codice errato: lancio annullato."
        if self.active is not None:
            self.after_action()

    def mouse(self) -> None:
        """Empire-style mouse. Left click: on one of your units selects it;
        next to the active unit moves (or attacks) there; farther away shows
        the route and a second click on the same cell sends the unit. Drag to
        pan the map, wheel to scroll it, right click to select."""
        try:
            _, mx, my, _, state = curses.getmouse()
        except curses.error:
            return
        mw, mh = self.map_size()
        inside = 1 <= my <= mh and 0 <= mx < mw
        wheel_up = getattr(curses, "BUTTON4_PRESSED", 0)
        wheel_down = getattr(curses, "BUTTON5_PRESSED", 0)
        if state & wheel_up or state & wheel_down:
            self.view_y = max(0, min(self.view_y + (-3 if state & wheel_up else 3),
                                     max(0, self.w.height - mh)))
            return
        if self.mode == "overview":
            if state & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED) and inside:
                kx, ky, _, _ = getattr(self, "overview_geom", (2, 2, 0, 0))
                y = min(self.w.height - 1, (my - 1) * 4 * ky + 2 * ky)
                self.cursor = self.w.idx(mx * 2 * kx + kx, y)
                self.mode = "normal"
                self.center()
            return
        if state & curses.BUTTON1_PRESSED and inside and self._pan is None:
            self._pan = (mx, my)
            self._pan_view = (self.view_x, self.view_y)
            self._dragged = False
            return
        if self._pan is not None and not state & (curses.BUTTON1_RELEASED | curses.BUTTON1_CLICKED):
            px, py = self._pan
            # a wobble of one cell is still a click; more than that drags
            if inside and (getattr(self, "_dragged", False) or max(abs(mx - px), abs(my - py)) > 1):
                self._dragged = True
                base_x, base_y = self._pan_view
                self.view_x = (base_x - (mx - px)) % self.w.width
                self.view_y = max(0, min(base_y - (my - py), max(0, self.w.height - mh)))
            return
        if state & (curses.BUTTON1_RELEASED | curses.BUTTON1_CLICKED):
            dragged = self._pan is not None and getattr(self, "_dragged", False)
            self._pan = self._pan_view = None
            self._dragged = False
            if dragged:
                cell = self._cell_at(mx, my) if inside else None
                if cell is not None:
                    self.cursor = cell   # the cursor lands where the hand let go
            elif inside:
                self.click(self._cell_at(mx, my))
            return
        if state & (curses.BUTTON3_PRESSED | curses.BUTTON3_CLICKED) and inside:
            cell = self._cell_at(mx, my)
            if cell is not None:
                self.cursor = cell
                if self.mode == "normal" and self.my_turn():
                    self.select_at_cursor()

    def _cell_at(self, mx: int, my: int) -> int | None:
        y = self.view_y + my - 1
        if y >= self.w.height:
            return None
        return self.w.idx(self.view_x + mx, y)

    def click(self, cell: int | None) -> None:
        if cell is None:
            return
        g = self.g
        if self.mode in ("goto", "nuke", "chem"):
            if cell == self.cursor:
                self.confirm_target()        # second click on the target: go
            else:
                self.cursor = cell
                self.status = "Clicca di nuovo sulla stessa casella per confermare."
            return
        self.cursor = cell
        if not self.my_turn():
            return
        a = self.active
        mine = [u for u in g.units_at(cell) if u.owner == self.viewer]
        if mine and (a is None or cell != a.cell) and not (a is not None and g.city(cell) is not None
                                                           and cell in self.w.neighbors[a.cell]):
            self.select_at_cursor()          # pick up one of your units
            return
        if a is None:
            return
        if cell == a.cell:
            self.select_at_cursor()          # click again: next unit in the stack
            return
        if cell in self.w.neighbors[a.cell]:
            ax, ay = self.w.xy(a.cell)
            cx, cy = self.w.xy(cell)
            dx = (cx - ax + self.w.width // 2) % self.w.width - self.w.width // 2
            self.move_active(dx, cy - ay)
            return
        if g.path(a, cell) is None:
            self.status = "Destinazione irraggiungibile per questa unità."
            return
        self.mode = "goto"                   # show the route; a second click sends it
        self.status = "Percorso mostrato: clicca di nuovo sulla casella per partire (Esc annulla)."

    def save(self) -> None:
        result = self.session.do(self.viewer, {"op": "save"})
        if self.session.online:
            self.status = "Partita salvata sul server." if result == "saved" else \
                "Il server non salva questa partita."
        else:
            self.status = f"Partita salvata in {self.session.save_path}"

    # ----------------------------------------------------------- loop
    def run(self) -> None:
        if self.session.online:
            self.scr.timeout(300)
            if not self.lobby():
                return
        else:
            self.session.start(self._progress)
            if getattr(self.session, "turn_time", 0):
                self.scr.timeout(500)  # wake up to tick the turn timer
        self.sync()
        self.center()
        while not self.quit:
            self.draw()
            key = self.scr.getch()
            self.tick_clock()
            if self.session.poll():
                self.sync()
            if self.session.closed and not self.quit:
                self.dialog("Connessione persa", [self.session.error or "Il server non risponde.",
                                                  "Rilancia con --join per rientrare."])
                return
            if key != -1:
                self.handle(key)

    def tick_clock(self) -> None:
        """Turn timer: a warning near the end, then the turn ends by itself.
        Online the server keeps the time; here only the warning plays."""
        left = self.session.seconds_left()
        if left is None or not self.my_turn():
            return
        if left <= 10 and not getattr(self, "warned", False):
            self.warned = True
            self.audio.sfx("alert")
            self.status = f"⏱ Restano {left} secondi!"
        if left == 0 and not self.session.online and self.mode in ("normal", "overview"):
            self.mode = "normal"
            self.status = "⏱ Tempo scaduto: turno finito."
            self.end_human_turn()

    def lobby(self) -> bool:
        """Wait for every seat to be taken. False if the player quits."""
        while not self.session.started:
            self.session.poll()
            if self.session.closed:
                return False
            self.scr.erase()
            h, w = self.scr.getmaxyx()
            g = self.g
            lines = [f"THE EMPIRE · partita online · {g.scenario.name}", "",
                     f"Server: {self.session.address}",
                     f"Tu giochi con: {g.factions[self.viewer].name}", "",
                     "Posti:"]
            for seat in self.session.lobby:
                who = seat["name"] if seat["taken"] else "— libero —"
                state = "" if not seat["taken"] else (" ●" if seat["online"] else " (offline)")
                lines.append(f"  {g.factions[seat['faction']].name:24s} {who}{state}")
            ai = [f.name for f in g.factions if not f.human]
            if ai:
                lines += ["", "Guidati dall'IA: " + ", ".join(ai)]
            lines += ["", "In attesa degli altri giocatori...  (Q per uscire)"]
            for k, line in enumerate(lines):
                self.put(2 + k, 4, line, curses.A_BOLD if k == 0 else 0)
            self.scr.refresh()
            self.audio.music("menu")
            key = self.scr.getch()
            if key in (ord("Q"), ord("q")):
                return False
            if key == ord("M"):
                self.music_menu()
        return True


SOUND_PRIORITY = ("nuke", "fall", "capture", "loss", "intercept", "gas", "crash",
                  "truce", "alert", "battle")


def pick_sound(g, viewer: int, events) -> str | None:
    """The one effect worth playing for these new events, from the point of
    view of ``viewer``: our conquests sound like victory, our losses like
    loss, and other people's distant wars stay quiet."""
    me = g.factions[viewer].name
    heard = set()
    fire: list[str] = []
    for e in events:
        sound = e.sound
        if sound == "capture":
            if e.actor == viewer:
                heard.add("capture")
            elif f"(prima: {me})" in e.text:
                heard.add("loss")
        elif sound == "fall":
            heard.add("loss" if e.actor == viewer else "fall")
        elif sound == "truce" and me not in e.text:
            continue
        elif sound == "battle" and e.kind:
            heard.add("battle")
            fire.append(f"fire_{e.kind}")
        elif sound:
            heard.add(sound)
    best = next((n for n in SOUND_PRIORITY if n in heard), None)
    if best == "battle" and fire:
        return fire[-1]   # the guns of whoever attacked last
    return best


def defcon(minutes: int) -> int:
    if minutes >= 10:
        return 4
    if minutes >= 7:
        return 3
    if minutes >= 4:
        return 2
    return 1


# --------------------------------------------------------------- start menu
def menu(scr, title: str, options: list[tuple[str, str]], intro: list[str] | None = None) -> int | None:
    """A simple vertical menu; returns the chosen index or None on Esc."""
    curses.curs_set(0)
    scr.keypad(True)
    k = 0
    while True:
        scr.erase()
        h, w = scr.getmaxyx()
        logo = [
            "████ █  █ ███    ███ █   █ ████ ███ ████ ███",
            " ██  ████ ██     ██  ██ ██ ██▄█  █  ██▄▀ ██ ",
            " ██  █  █ ███    ███ █ ▀ █ █    ███ █ ▀▄ ███",
        ]
        y = 1
        for line in logo:
            try:
                scr.addstr(y, max(0, (w - len(line)) // 2), line[: w - 1], curses.A_BOLD)
            except curses.error:
                pass
            y += 1
        y += 1
        try:
            scr.addstr(y, max(0, (w - len(title)) // 2), title[: w - 1], curses.A_BOLD)
        except curses.error:
            pass
        y += 2
        for line in intro or []:
            try:
                scr.addstr(y, 4, line[: w - 6])
            except curses.error:
                pass
            y += 1
        if intro:
            y += 1
        for j, (label, desc) in enumerate(options):
            attr = curses.A_REVERSE | curses.A_BOLD if j == k else 0
            try:
                scr.addstr(y, 4, f" {label} "[: w - 6], attr)
                if desc:
                    scr.addstr(y + 1, 8, desc[: w - 10], curses.A_DIM)
            except curses.error:
                pass
            y += 3 if desc else 1
        try:
            scr.addstr(h - 1, 2, "↑↓ scegli · Invio conferma · Esc indietro"[: w - 3], curses.A_DIM)
        except curses.error:
            pass
        scr.refresh()
        key = scr.getch()
        if key in (curses.KEY_UP, ord("w"), ord("k")):
            k = (k - 1) % len(options)
        elif key in (curses.KEY_DOWN, ord("x"), ord("j")):
            k = (k + 1) % len(options)
        elif key in (10, 13, curses.KEY_ENTER):
            return k
        elif key in (27, ord("q")):
            return None


def setup_menu(scr) -> dict | None:
    while True:
        keys = list(SCENARIOS)
        k = menu(scr, "Scegli lo scenario",
                 [(SCENARIOS[s].name, SCENARIOS[s].description) for s in keys]
                 + [("Carica la partita salvata", str(SAVE_PATH))])
        if k is None:
            return None
        if k == len(keys):
            return {"load": SAVE_PATH}
        sc = SCENARIOS[keys[k]]
        f = menu(scr, f"{sc.name}: scegli la tua fazione",
                 [(fd.name, _faction_blurb(fd)) for fd in sc.factions])
        if f is None:
            continue
        d = menu(scr, "Difficoltà", [("facile", "IA con industria al 75%"),
                                     ("normale", "IA alla pari"),
                                     ("difficile", "IA con industria al 130%")])
        if d is None:
            continue
        times = (0, 60, 120, 180, 300)
        t = menu(scr, "Tempo per turno", [
            ("Nessun limite", "pensa quanto vuoi"),
            ("1 minuto", "guerra lampo: decisioni di istinto"),
            ("2 minuti", "ritmo serrato"),
            ("3 minuti", "il giusto equilibrio"),
            ("5 minuti", "per imperi grandi")])
        if t is None:
            continue
        return {"scenario": sc.key, "humans": (sc.factions[f].key,),
                "difficulty": ("facile", "normale", "difficile")[d], "turn_time": times[t]}


def _faction_blurb(fd) -> str:
    doctrine = {"restrained": "dottrina prudente", "balanced": "dottrina equilibrata",
                "aggressive": "dottrina aggressiva"}[fd.doctrine]
    parts = [doctrine]
    if fd.warheads:
        parts.append(f"{fd.warheads} testate")
    if fd.industry != 1.0:
        parts.append(f"economia di guerra ×{fd.industry:g}")
    if fd.capital_city:
        parts.append(f"capitale {fd.capital_city}")
    return ", ".join(parts)
