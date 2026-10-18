"""Curses interface: Braille world map, side panel, event log and menus."""

from __future__ import annotations

import curses
import datetime as dt
import json
import random
import textwrap
import time
from collections import Counter, deque
from pathlib import Path

from theempire import cards, events, i18n, missions, regions
from theempire.audio import Audio, music_keys, music_name
from theempire.commands import describe
from theempire.game import CHEM_RANGE, DIRECTIVES, Unit
from theempire.i18n import N, tr, word
from theempire.scenarios import SCENARIOS
from theempire.tutorial import Tutorial
from theempire.units import (ASAT, CHEMICAL, PRODUCTION_NAMES, SATELLITE, SYMBOLS,
                             UNIT_TYPES, WARHEAD, production_cost)
from theempire.world import load_hd

SIDEBAR = 36
BLINK_MS = 200          # the screen wakes this often; the active unit blinks twice as slowly
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

HELP = N("""\
MENU              ↑↓ per scegliere, Invio per confermare (o la lettera/il numero), Esc
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
K                 carte: diserzione, rivolta, spionaggio, piano quinquennale...
B                 bollettini di guerra: leggili, sfoglia i turni, R per rivederli
T                 chat con gli altri giocatori (partite online)
P                 direttiva di produzione: aria, terra, mare, sbarchi, difesa...
g                 vai a... (sposta il cursore, Invio per confermare)
v                 sveglia le unità sotto il cursore (anche il carico)
l / u             carica / scarica un trasporto o portaerei in città
p                 produzione della città sotto il cursore
D                 congeda l'unità attiva
m                 mappa del mondo (panoramica)
+ / -             zoom della mappa (anche pulsanti nel pannello, pizzico)
r                 centra la vista sul cursore
o                 obiettivo segreto, regioni (bonus) ed eventi mondiali
Z                 spazio: satelliti spia e armi antisatellite
V                 unità con simboli (♟ ♜ ✈ ▼ ▸ ◒ ▭ ⧫ ▬ ✧ ➶) o con lettere
M                 audio: scegli musica ed effetti
L                 lingua dell'interfaccia (language)
N                 ☢ attacco nucleare sulla casella del cursore
C                 ☣ attacco chimico (entro 4 caselle dalle tue forze)
E                 fine turno
S / Q             salva / esci          ? questo aiuto

Attaccare: muovi un'unità su una casella nemica. Solo fanteria e corazzati
conquistano le città. Le navi entrano solo nei porti amici; gli aerei
consumano carburante e si riforniscono in città o sulle portaerei.
Ogni arma di distruzione di massa avvicina l'Orologio dell'Apocalisse
alla mezzanotte: a 0 minuti la guerra nucleare totale distrugge tutti.""")

# Month abbreviations for the date in the title bar (one key, split after translation).
MONTHS = N("gen feb mar apr mag giu lug ago set ott nov dic")


BRAILLE_DOTS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))  # [column][row]


def _longitude(lon: float) -> str:
    return f"{abs(lon):.0f}°{'E' if lon >= 0 else 'W'}"


def load_setting(key: str, default):
    """A display preference kept in ~/.theempire/settings.json."""
    try:
        data = json.loads(i18n.SETTINGS.read_text(encoding="utf-8"))
        return data.get(key, default) if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def save_setting(key: str, value) -> None:
    try:
        data = json.loads(i18n.SETTINGS.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data[key] = value
    try:
        i18n.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        i18n.SETTINGS.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def lower_noun(name: str) -> str:
    """A unit name inside a sentence: lower case, except in German, where
    nouns keep their capital letter."""
    return name if i18n.language() == "de" else name.lower()


def zoom_tile(world, cell: int, k: int) -> tuple[str, ...]:
    """The land of a cell drawn k × k characters large, as rows of Braille.

    Like Terrascope, the zoom samples the coastline again at the finer scale
    (the land mask of world.load_hd) instead of blowing up the dots of the
    normal map; without that file the dots are only magnified."""
    hd = load_hd()
    cx, cy = world.xy(cell)
    rows = []
    for j in range(k):
        row = ""
        for i in range(k):
            bits = 0
            for tc in range(2):
                for tw in range(4):
                    if hd is not None and hd.zoom % k == 0:
                        s = hd.zoom // k                     # samples per dot, each way
                        x0 = cx * 2 * hd.zoom + (i * 2 + tc) * s
                        y0 = cy * 4 * hd.zoom + (j * 4 + tw) * s
                        land = sum(hd.land(x0 + a, y0 + b) for a in range(s) for b in range(s))
                        on = land * 2 >= s * s
                    else:
                        dots = world.dots[cell] or (0xFF if world.land[cell] else 0)
                        on = bool(dots & BRAILLE_DOTS[(i * 2 + tc) // k][(j * 4 + tw) // k])
                    if on:
                        bits |= BRAILLE_DOTS[tc][tw]
            row += chr(0x2800 + bits) if bits else " "
        rows.append(row)
    return tuple(rows)


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
        self.pending_card: str | None = None
        self.tutorial: Tutorial | None = None
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
        try:
            curses.set_escdelay(25)   # Esc closes menus at once
        except (AttributeError, curses.error):
            pass
        # Motion reports are needed to drag the map while the button is held.
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.mouseinterval(0)
        # The terminfo of most terminals only turns on mode 1000 (clicks):
        # ask for 1002 too, so the terminal reports the drag while it happens.
        # ncurses switches the mouse on at the first getch, and a later 1000
        # would cancel 1002: read once now, then ask (draw() asks again).
        self.scr.nodelay(True)
        pending = self.scr.getch()
        self.scr.nodelay(False)
        if pending != -1:
            curses.ungetch(pending)
        self._terminal(b"\x1b[?1002h")
        self.hotspots: list[tuple[int, int, int, object]] = []
        self.last_mouse = (0, 0, 0)

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
        if g.realtime:          # no turns: always time to give orders
            return not g.over and g.factions[self.viewer].alive and getattr(self.session, "started", True)
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

    # Zoom levels: one cell of the map takes k × k characters, so the map
    # keeps its proportions; the coast is redrawn with finer detail.
    ZOOMS = (1, 2, 4)

    @property
    def _tiles(self) -> dict:
        """Zoomed land drawings, made once per cell and zoom level."""
        return self.__dict__.setdefault("_tile_cache", {})

    def zoom_factor(self) -> tuple[int, int]:
        k = self.ZOOMS[getattr(self, "zoom", 0)]
        return k, k

    def view_size(self) -> tuple[int, int]:
        """How many cells of the map are on screen (wide, high)."""
        mw, mh = self.map_size()
        zx, zy = self.zoom_factor()
        return max(1, mw // zx), max(1, mh // zy)

    def set_zoom(self, step: int, at: tuple[int, int] | None = None) -> None:
        """Zoom in (step > 0) or out. With ``at`` (a point on the screen, as
        with Ctrl+wheel or a pinch) the cell under it stays under it;
        otherwise the view centres on the cursor."""
        zoom = max(0, min(len(self.ZOOMS) - 1, getattr(self, "zoom", 0) + step))
        if zoom == getattr(self, "zoom", 0):
            self.status = tr("Zoom massimo.") if step > 0 else tr("Zoom minimo: m mostra il mondo intero.")
            return
        anchor = self._cell_at(*at) if at is not None else None
        self.zoom = zoom
        self.status = tr("Zoom ×{factor}.", factor=self.ZOOMS[zoom])
        if anchor is None:
            self.center()
            return
        mx, my = at
        zx, zy = self.zoom_factor()
        cx, cy = self.w.xy(anchor)
        rows = self.view_size()[1]
        self.view_x = (cx - mx // zx) % self.w.width
        self.view_y = max(0, min(cy - (my - 1) // zy, max(0, self.w.height - rows)))

    def follow_cursor(self) -> None:
        mw, mh = self.view_size()
        cx, cy = self.w.xy(self.cursor)
        rel = (cx - self.view_x) % self.w.width
        if rel < 3 or rel > mw - 4:
            self.view_x = (cx - mw // 2) % self.w.width
        if cy < self.view_y + 2 or cy > self.view_y + mh - 3:
            self.view_y = cy - mh // 2
        self.view_y = max(0, min(self.view_y, max(0, self.w.height - mh)))

    def center(self) -> None:
        mw, mh = self.view_size()
        cx, cy = self.w.xy(self.cursor)
        self.view_x = (cx - mw // 2) % self.w.width
        self.view_y = max(0, min(cy - mh // 2, max(0, self.w.height - mh)))

    def date_text(self) -> str:
        start = START_DATES.get(self.g.scenario.key)
        if start is None:
            return tr("Anno {year}, sett. {week}", year=1 + (self.g.turn - 1) // 52,
                      week=1 + (self.g.turn - 1) % 52)
        d = start + dt.timedelta(weeks=self.g.turn - 1)
        months = tr(MONTHS).split()
        if len(months) != 12:      # a broken translation
            months = MONTHS.split()
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

    def button(self, y: int, x: int, text: str, action, attr: int = 0) -> None:
        """Text that can be clicked: ``action`` is a key (as typed) or a
        function to call."""
        self.put(y, x, text, attr)
        self.hotspots.append((y, x, x + len(text), action))

    def hotspot(self, mx: int, my: int):
        for y, x0, x1, action in reversed(getattr(self, "hotspots", ())):
            if y == my and x0 <= mx < x1:
                return action
        return None

    def press(self, action) -> None:
        """Do what a clicked label stands for."""
        if callable(action):
            action()
        else:
            self.handle(ord(action) if isinstance(action, str) else action)

    def read_key(self, win) -> int:
        """getch for dialogs and menus: the wheel scrolls (↑↓), a click
        counts when the button comes up (its position is in last_mouse),
        the press alone is ignored so that it cannot leak elsewhere."""
        while True:
            key = win.getch()
            if key != curses.KEY_MOUSE:
                return key
            try:
                _, mx, my, _, state = curses.getmouse()
            except curses.error:
                continue
            if state & getattr(curses, "BUTTON4_PRESSED", 0):
                return curses.KEY_UP
            if state & getattr(curses, "BUTTON5_PRESSED", 0):
                return curses.KEY_DOWN
            if state & (curses.BUTTON1_RELEASED | curses.BUTTON1_CLICKED):
                self.last_mouse = (mx, my, state)
                return curses.KEY_MOUSE

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
        self.hotspots = []
        self.scr.erase()
        if self.mode == "overview":
            self.draw_overview()
        else:
            self.draw_map()
        self.draw_tutorial()
        self.draw_top()
        self.draw_sidebar()
        self.draw_log()
        self.draw_status()
        self.scr.refresh()
        self._terminal(b"\x1b[?1002h")   # in case ncurses reset the mouse mode

    def draw_tutorial(self) -> None:
        """The instructor's box, in the top-left corner of the map."""
        tutorial = getattr(self, "tutorial", None)
        box = tutorial.box() if tutorial else None
        if box is None:
            return
        title, lines = box
        mw, mh = self.map_size()
        width = min(mw - 2, max(len(title) + 4, *(len(line) + 4 for line in lines)))
        if width < 30 or mh < len(lines) + 4:
            return
        attr = self.color("white", "sea") if self.rich else curses.A_REVERSE
        self.put(1, 1, "┌" + "─" * (width - 2) + "┐", attr)
        self.put(1, 3, title[: width - 6], attr | curses.A_BOLD)
        for k, line in enumerate(lines):
            self.put(2 + k, 1, "│ " + line[: width - 4].ljust(width - 4) + " │", attr)
        self.put(2 + len(lines), 1, "└" + "─" * (width - 2) + "┘", attr)

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
            return self.glyph(kind), self.color(self.owner_color(owner), bg) | curses.A_BOLD
        if self.active is not None and self.active.cell == cell and self.active.id in g.units:
            lit = curses.A_REVERSE if self.blink_on() else 0      # the active unit blinks
            return self.glyph(self.active.kind), self.color(self.owner_color(self.active.owner), bg) | curses.A_BOLD | lit
        if city is not None:
            glyph = "★" if city.capital else "◉" if city.size == 3 else "●" if city.size == 2 else "•"
            attr = self.color(self.owner_color(city.owner) if city.owner is not None else "white", bg) | curses.A_BOLD
            if any(u.owner == self.viewer for u in g.units_at(cell)):
                attr |= curses.A_UNDERLINE
            return glyph, attr
        if units:
            # an aircraft flying over a unit is drawn on top
            u = next((o for o in units if o.type.domain == "air"), units[0])
            return self.glyph(u.kind), self.color(self.owner_color(u.owner), bg) | curses.A_BOLD
        if cell in path:
            return "·", self.color("white", bg) | curses.A_BOLD
        if cell in g.fallout:
            return "☢", self.color("fallout", bg) | dim
        return self.ground_glyph(cell, seen)

    def ground_glyph(self, cell: int, seen: bool) -> tuple[str, int]:
        """The land or sea of a cell, without what stands on it."""
        g = self.g
        land = self.w.land[cell]
        bg = None if land or not self.rich else "sea"
        dim = 0 if seen else curses.A_DIM
        dots = self.w.dots[cell]
        if land:
            src = self.territory_source[cell]
            owner = g.cities[src].owner if src >= 0 else None
            return chr(0x2800 + (dots or 0xFF)), self.color(self.owner_color(owner)) | dim
        if dots:
            return chr(0x2800 + dots), self.color("coast", bg) | dim
        return " ", self.color("white", bg)

    @property
    def symbols(self) -> bool:
        """Units drawn as symbols (♟ ♜ ✈...) rather than letters (I A F...)."""
        if "_symbols" not in self.__dict__:
            self._symbols = load_setting("unit_symbols", True)
        return self._symbols

    def glyph(self, kind: str) -> str:
        return SYMBOLS.get(kind, kind) if self.symbols else kind

    def toggle_symbols(self) -> None:
        self._symbols = not self.symbols
        save_setting("unit_symbols", self._symbols)
        self.status = tr("Unità disegnate con simboli.") if self._symbols else \
            tr("Unità disegnate con lettere.")

    @staticmethod
    def blink_on() -> bool:
        """The phase of the active unit's blinking."""
        return int(time.monotonic() * 1000 / BLINK_MS / 2) % 2 == 0

    def zoom_attrs(self, cell: int, seen: bool) -> tuple[int, int]:
        """Colours of a zoomed cell: (solid land, land against the sea).
        The land dots of a sea cell belong to the land next to it."""
        dim = 0 if seen else curses.A_DIM
        src_cell = cell if self.w.land[cell] else next(
            (n for n in self.w.neighbors[cell] if self.w.land[n]), None)
        if src_cell is None:
            return (self.color("coast", "sea" if self.rich else None) | dim,) * 2
        src = self.territory_source[src_cell]
        owner = self.g.cities[src].owner if src >= 0 else None
        fg = self.owner_color(owner)
        return self.color(fg) | dim, self.color(fg, "sea" if self.rich else None) | dim

    def draw_map(self) -> None:
        g = self.g
        mw, mh = self.map_size()
        vis = g.visible(self.viewer) | self.reveal
        path: set[int] = set()
        if self.mode == "goto" and self.active is not None and self.active.id in g.units:
            route = g.path(self.active, self.cursor) or []
            path = set(route[:-1])
        zx, zy = self.zoom_factor()
        cols, rows = self.view_size()
        for sy in range(rows):
            y = self.view_y + sy
            if y >= self.w.height:
                break
            for sx in range(cols):
                cell = y * self.w.width + (self.view_x + sx) % self.w.width
                ch, attr = self.cell_glyph(cell, vis, path)
                gattr = sattr = attr
                if zx > 1:
                    gattr, sattr = self.zoom_attrs(cell, cell in vis)
                mark = 0
                if cell == self.cursor:
                    mark = curses.A_REVERSE if self.mode == "normal" else -1
                    if mark == curses.A_REVERSE and self.active is not None \
                            and self.active.cell == cell and not self.blink_on():
                        mark = 0         # the cursor on the active unit blinks with it
                    if self.mode in ("nuke", "chem"):
                        ch = "✕"
                elif self.mode in ("nuke", "chem") and self.w.dist(cell, self.cursor) == 1:
                    mark = curses.A_REVERSE
                if mark == -1:
                    attr = gattr = sattr = self.color("alert") | curses.A_REVERSE | curses.A_BOLD
                elif mark:
                    attr, gattr, sattr = attr | mark, gattr | mark, sattr | mark
                if zx == 1:
                    self.put(1 + sy, sx, ch, attr)
                    continue
                # zoomed in: the cell is a block of finer coastline, and what
                # stands on it (unit, city...) sits in its middle
                tile = self._tiles.get((cell, zx))
                if tile is None:
                    tile = self._tiles[(cell, zx)] = zoom_tile(self.w, cell, zx)
                plain = ch == self.ground_glyph(cell, cell in vis)[0]
                mid = (zx - 1) // 2
                for j, row in enumerate(tile):
                    for i, dot in enumerate(row):
                        if not plain and i == mid and j == mid:
                            self.put(1 + sy * zy + j, sx * zx + i, ch, attr)
                        else:
                            self.put(1 + sy * zy + j, sx * zx + i, dot, gattr if dot == "⣿" else sattr)

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
        self.put(1 + min(rows, mh), 0, tr("Panoramica: clic o frecce per scegliere, Invio/m per tornare"),
                 self.color("dim"))

    def draw_top(self) -> None:
        g = self.g
        h, w = self.scr.getmaxyx()
        self.put(0, 0, " " * (w - 1), curses.A_REVERSE)
        title = " " + tr("THE EMPIRE · {scenario} · {date} · turno {turn}", scenario=g.scenario.name,
                         date=self.date_text(), turn=g.turn) + " "
        self.put(0, 0, title, curses.A_REVERSE | curses.A_BOLD)
        minutes = max(0, g.doomsday)
        clock = " " + tr("☢ 23:{minute:02d}  {minutes} MIN A MEZZANOTTE  DEFCON {defcon}",
                         minute=60 - minutes, minutes=minutes, defcon=defcon(minutes)) + " "
        level = "alert" if minutes <= 3 else "fallout" if minutes <= 6 else "good"
        self.put(0, max(len(title) + 1, w - len(clock) - 1), clock, self.color(level) | curses.A_REVERSE | curses.A_BOLD)
        if g.realtime and not g.over:
            self.put(0, len(title), " " + tr("⚡ tempo reale · impulso {turn}", turn=g.turn) + " ",
                     curses.A_REVERSE | curses.A_BOLD)
        elif g.current != self.viewer and not g.over:
            self.put(0, len(title), " " + tr("⌛ tocca a {faction}", faction=g.faction.name) + " ",
                     curses.A_REVERSE)
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
        self.put(row, x, word(fac.name).upper()[:SIDEBAR - 1], self.color(fac.color) | curses.A_BOLD)
        row += 1
        cities = g.cities_of(self.viewer)
        industry = sum(g.production_rate(c) for c in cities)
        units = g.units_of(self.viewer)
        self.put(row, x, tr("Città {n:3d}  industria {rate:5.1f}/turno", n=len(cities), rate=industry))
        row += 1
        self.put(row, x, tr("Unità {n:3d}/{limit}  ☢ {warheads:2d}  ☣ {chemicals}", n=len(units),
                            limit=g.supply_limit(self.viewer), warheads=fac.warheads, chemicals=fac.chemicals))
        row += 1
        if g.scenario.modern:
            self.button(row, x, tr("⊙ Satelliti {n} · antisatellite {asats} (Z)", n=len(fac.satellites),
                                   asats=fac.asats)[:SIDEBAR - 1], "Z", self.color("cyan"))
            row += 1
        effects = []
        if cards.active(g, self.viewer, "plan"):
            effects.append(tr("piano"))
        if cards.active(g, self.viewer, "shield"):
            effects.append(tr("scudo"))
        spied = cards.spied(g, self.viewer)
        if spied is not None:
            effects.append(tr("spie su {faction}", faction=word(g.factions[spied].name).split()[-1]))
        hand = tr("Carte ♠ {n}/{limit} (K)", n=len(fac.cards), limit=cards.HAND_LIMIT)
        self.button(row, x, (hand + ("  " + ", ".join(effects) if effects else ""))[:SIDEBAR - 1], "K",
                    self.color("cyan") if fac.cards else self.color("dim"))
        row += 1
        label = word(DIRECTIVES[fac.directive]).split(" (")[0] if fac.directive else tr("nessuna")
        self.button(row, x, tr("Direttiva: {directive} (P)", directive=label)[:SIDEBAR - 1], "P",
                    self.color("dim"))
        row += 1
        if fac.mission.get("kind") in ("regions", "eliminate", "cities", "capitals"):
            self.button(row, x, f"◎ {missions.progress(g, self.viewer)} (o)"[:SIDEBAR - 1], "o",
                        self.color("cyan") | curses.A_BOLD)
            row += 1
        held = regions.held_by(g, self.viewer)
        if held:
            pct = int(round(regions.production_bonus(g, self.viewer) * 100))
            text = tr("⚑ {regions} +{pct}%", regions=", ".join(word(regions.REGIONS[k].short) for k in held),
                      pct=pct)
        else:
            near = next(((k, n, t) for k, n, t in regions.progress(g, self.viewer) if n < t), None)
            text = tr("⚑ {region} {n}/{total} città", region=regions.REGIONS[near[0]].short,
                      n=near[1], total=near[2]) if near else tr("⚑ Regioni")
        self.button(row, x, (text + " (o)")[:SIDEBAR - 1], "o", self.color("dim"))
        row += 1
        world = events.describe_active(g)
        if world:
            self.button(row, x, ("✦ " + ", ".join(world))[:SIDEBAR - 1], "o", self.color("cyan"))
            row += 1
        others = [f for f in g.factions if f.idx != self.viewer]
        names = self.session.player_names()
        for f in others:
            state = tr("{n:3d} città", n=len(g.cities_of(f.idx))) if f.alive else tr("  sconfitto")
            mark = "≈" if g.truce_left(self.viewer, f.idx) else " "
            hand = f" ♠{len(f.cards)}" if f.alive and f.cards else ""
            self.button(row, x, f"{word(f.name)[:21]:21s}{mark}{state}{hand}"[:SIDEBAR - 1], "O",
                        self.color(f.color))
            row += 1
            if f.idx in names:
                self.put(row, x, tr("  giocatore: {name}", name=names[f.idx])[:SIDEBAR - 1], self.color("dim"))
                row += 1
        self.put(row, x, f"{word(g.faction_name(None)):22s}" + tr("{n:3d} città", n=len(g.cities_of(None))),
                 self.color("neutral"))
        row += 1
        self.put(row, x, "─" * (SIDEBAR - 1), self.color("dim"))
        row += 1
        waiting = len(self.needing_orders())
        self.button(row, x, tr("In attesa di ordini: {n} (n)", n=waiting), "n",
                    curses.A_BOLD if waiting else self.color("dim"))
        row += 1
        a = self.active
        if a is not None and a.id in g.units:
            row = self._unit_lines(a, row, x, active=True)
            odds = g.odds(a, self.cursor) if self.cursor in self.w.neighbors[a.cell] else None
            if odds is not None:
                self.put(row, x, tr("⚔ Probabilità di vittoria: {pct:3.0f}%", pct=odds * 100),
                         self.color("good" if odds >= 0.6 else "fallout" if odds >= 0.35 else "alert") | curses.A_BOLD)
                row += 1
        self.put(row, x, "─" * (SIDEBAR - 1), self.color("dim"))
        row += 1
        bottom = self._command_buttons(x, h - 2)
        row = self._cell_lines(self.cursor, row, x, bottom)

    COMMANDS = (("E", N("Fine turno")), ("B", N("Bollettino")), ("O", N("Diplomazia")), ("m", N("Mondo")),
                ("+", N("Zoom")), ("-", N("Zoom")), ("M", N("Audio")), ("S", N("Salva")), ("?", N("Aiuto")))

    def _command_buttons(self, x: int, last: int) -> int:
        """The clickable command bar at the foot of the panel; returns the
        first row it takes."""
        rows, line = [], []
        for key, label in self.COMMANDS:
            text = f" {tr(label)} {key} "
            if line and sum(len(t) + 1 for t, _ in line) + len(text) > SIDEBAR - 1:
                rows.append(line)
                line = []
            line.append((text, key))
        rows.append(line)
        top = last - len(rows) + 1
        for k, line in enumerate(rows):
            cx = x
            for text, key in line:
                self.button(top + k, cx, text, key, self.color("panel") | curses.A_REVERSE)
                cx += len(text) + 1
        return top

    def _unit_lines(self, u: Unit, row: int, x: int, active: bool = False) -> int:
        g = self.g
        t = u.type
        mine = u.owner == self.viewer
        label = ("▶ " if active else "  ") + self.glyph(u.kind) + " " + word(t.name)
        if not mine:
            label += f" ({word(g.factions[u.owner].name)})"
        attr = self.color(self.owner_color(u.owner)) | (curses.A_BOLD if active else 0)
        if mine:
            self.button(row, x, label[:SIDEBAR - 1], lambda: self.take_command(u), attr)
        else:
            self.put(row, x, label[:SIDEBAR - 1], attr)
        row += 1
        if mine:
            info = "    " + tr("PV {hp}/{max_hp}  mosse {moves}/{max_moves}", hp=u.hp, max_hp=t.hp,
                                  moves=u.moves, max_moves=t.move)
            if t.domain == "air":
                info += "  " + tr("carb. {fuel}", fuel=u.fuel)
            self.put(row, x, info)
            row += 1
            extra = {"sentry": N("sentinella"), "fortify": N("fortificata"), "goto": N("in marcia"),
                     "auto": N("automatica")}.get(u.order or "", "")
            extra = tr(extra) if extra else ""
            if u.cargo:
                kinds = Counter(g.units[c].kind for c in u.cargo if c in g.units)
                extra += " " + tr("carico {n}/{capacity}: {kinds}", n=len(u.cargo), capacity=t.capacity,
                                  kinds=" ".join(f"{n}{self.glyph(k)}" for k, n in kinds.items()))
            if extra:
                self.put(row, x, "    " + extra.strip(), self.color("dim"))
                row += 1
        return row

    def _cell_lines(self, cell: int, row: int, x: int, bottom: int) -> int:
        g = self.g
        lon, lat = self.w.lonlat(cell)
        country = self.w.country_of(cell)
        terrain = tr("terra") if self.w.land[cell] else tr("mare")
        where = f"{abs(lat):.0f}°{'N' if lat >= 0 else 'S'} {abs(lon):.0f}°{'E' if lon >= 0 else 'W'}"
        self.put(row, x, f"{where} · {terrain}" + (f" · {word(country['name'])}" if country else ""))
        row += 1
        if cell in g.fallout:
            self.put(row, x, tr("☢ ricaduta radioattiva ({turns} turni)", turns=g.fallout[cell]),
                     self.color("fallout"))
            row += 1
        city = g.city(cell)
        if city is not None:
            tag = " " + tr("★ capitale") if city.capital else ""
            self.put(row, x, f"{city.name}{tag}"[:SIDEBAR - 1], self.color(self.owner_color(city.owner)) | curses.A_BOLD)
            row += 1
            self.put(row, x, "  " + tr("{faction} · dimensione {size} · milizia {militia}",
                                       faction=g.faction_name(city.owner), size=city.size, militia=city.militia))
            row += 1
            if city.owner == self.viewer:
                cost = production_cost(city.production)
                rate = g.production_rate(city)
                eta = "∞" if rate <= 0 else str(max(0, -(-(cost - city.progress) // rate)))
                hand = " " + tr("(a mano)") if city.manual and g.factions[self.viewer].directive else ""
                self.button(row, x, ("  " + tr("Produce: {production}", production=PRODUCTION_NAMES[city.production])
                                     + hand + " (p)")[:SIDEBAR - 1], "p")
                row += 1
                self.put(row, x, "  " + tr("{progress:.0f}/{cost} punti, pronto in {eta} turni",
                                           progress=city.progress, cost=cost, eta=eta))
                row += 1
                notes = []
                if city.irradiated:
                    notes.append(tr("irradiata {turns}t", turns=city.irradiated))
                if city.unrest:
                    notes.append(tr("disordini {turns}t", turns=city.unrest))
                if notes:
                    self.put(row, x, "  " + ", ".join(notes), self.color("alert"))
                    row += 1
        units = [u for u in g.units_at(cell) if g.sees(self.viewer, u)]
        if city is not None and units and len(units) > 4:
            kinds = Counter((u.owner, u.kind) for u in units)
            text = "  " + tr("Guarnigione: {units}",
                             units=" ".join(f"{n}{self.glyph(k)}" for (_, k), n in kinds.items()))
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
            self.put(top, 2, " " + tr("BOLLETTINO DI GUERRA") + " ",
                     self.color("alert") | curses.A_REVERSE | curses.A_BOLD)
            for k, line in enumerate(self.ticker[-(LOG_ROWS - 1):]):
                attr = curses.A_BOLD if loud(line) or "☢" in line else 0
                self.put(top + 1 + k, 0, f" {line}"[:mw].ljust(mw), self.color("panel") | attr)
            return
        events = [e for e in self.g.events if e.audience is None or self.viewer in e.audience]
        colors = {"info": "panel", "combat": "orange", "alert": "alert", "wmd": "wmd", "chat": "cyan",
                  "world": "cyan"}
        for k, e in enumerate(events[-(LOG_ROWS - 1):]):
            self.put(top + 1 + k, 0, f"[{e.turn:3d}] {e.shown()}"[:mw].ljust(mw),
                     self.color(colors.get(e.level, "panel")) | (curses.A_BOLD if e.level in ("wmd", "alert", "world") else 0))

    def draw_status(self) -> None:
        h, w = self.scr.getmaxyx()
        hint = {
            "normal": N("qweadzxc muovi · frecce cursore · n prossima · g vai · p produzione · E fine turno · ? aiuto"),
            "goto": N("VAI A: sposta il cursore e premi Invio (Esc annulla)"),
            "nuke": N("☢ BERSAGLIO NUCLEARE: sposta il cursore e premi Invio (Esc annulla)"),
            "chem": N("☣ BERSAGLIO CHIMICO: sposta il cursore e premi Invio (Esc annulla)"),
            "card": N("♠ {card}: scegli il bersaglio e premi Invio (Esc annulla)"),
            "overview": N("PANORAMICA"),
        }[self.mode]
        hint = tr(hint, card=cards.CARDS[self.pending_card].name if self.pending_card else "")
        if self.status:
            self.put(h - 1, 0, self.status[: w - 1], curses.A_BOLD)
            return
        # "n prossima · g vai · ...": each hint led by a key can be clicked
        x = 0
        for k, part in enumerate(hint.split(" · ")):
            if k:
                self.put(h - 1, x, " · ", self.color("dim"))
                x += 3
            key = part.split(" ")[0]
            if len(key) == 1 and len(part) > 1 and x < w - 1:
                self.button(h - 1, x, part[: w - 1 - x], key, self.color("dim") | curses.A_UNDERLINE)
            else:
                self.put(h - 1, x, part, self.color("dim"))
            x += len(part)

    # ----------------------------------------------------------- dialogs
    def dialog(self, title: str, lines: list[str], footer: str = "") -> int:
        footer = footer or tr("premi un tasto")
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
        key = self.read_key(win)
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

    ENTER_KEYS = (10, 13, curses.KEY_ENTER)

    def choose(self, title: str, items: list[tuple[str, object, object]],
               header: list[str] | None = None, notes: list[str] | None = None,
               current=None, extra_keys: str = "", footer: str = ""):
        """A list to pick from: ↑↓ move, Invio confirms, the item's letter or
        number picks it at once, Esc cancels.

        ``items`` are (shortcut, text, value); text is a string or a list of
        lines (the first is the one highlighted). Returns ("item", value),
        ("key", ch) for one of ``extra_keys``, or None."""
        header, notes = header or [], notes or []
        rows = [[t] if isinstance(t, str) else list(t) for _, t, _ in items]
        sel = next((k for k, it in enumerate(items) if it[2] == current), 0)
        h, w = self.scr.getmaxyx()
        body = [*header, *([""] if header else [])]
        width = min(w - 4, max(len(title) + 6, len(footer) + 6,
                               *(len(line) + 10 for r in rows for line in r),
                               *(len(line) + 6 for line in header + notes)))
        height = min(h - 2, len(body) + sum(len(r) for r in rows) + len(notes) + (1 if notes else 0) + 4)
        win = curses.newwin(height, width, (h - height) // 2, (w - width) // 2)
        win.keypad(True)
        footer = footer or tr("↑↓ scegli · Invio conferma · lettera o numero diretti · Esc annulla")
        while True:
            win.erase()
            win.box()
            y = 2
            item_rows = {}
            try:
                win.addstr(0, 2, f" {title} "[: width - 4], curses.A_BOLD)
                for line in body:
                    if y < height - 1:
                        win.addstr(y, 2, line[: width - 4])
                    y += 1
                for k, (key, _, _) in enumerate(items):
                    for j, line in enumerate(rows[k]):
                        if y >= height - 1:
                            break
                        lead = f"{'▶' if k == sel else ' '} {key:>2}  " if j == 0 else "        "
                        text = (lead + line)[: width - 4].ljust(width - 4)
                        attr = curses.A_REVERSE | curses.A_BOLD if k == sel and j == 0 else \
                            (curses.A_DIM if j else 0)
                        win.addstr(y, 2, text, attr)
                        item_rows[y] = k
                        y += 1
                if notes:
                    y += 1
                    for line in notes:
                        if y < height - 1:
                            win.addstr(y, 2, line[: width - 4], curses.A_DIM)
                        y += 1
                win.addstr(height - 1, 2, f" {footer} "[: width - 4], curses.A_DIM)
            except curses.error:
                pass
            win.refresh()
            key = self.read_key(win)
            if key == curses.KEY_MOUSE:
                mx, my, _ = self.last_mouse
                wy, wx = win.getbegyx()
                if not (0 <= my - wy < height and 0 <= mx - wx < width):
                    result = None            # a click outside closes the menu
                    break
                if my - wy in item_rows:
                    result = ("item", items[item_rows[my - wy]][2])
                    break
                continue
            if key in (curses.KEY_UP, curses.KEY_LEFT):
                sel = (sel - 1) % len(items)
            elif key in (curses.KEY_DOWN, curses.KEY_RIGHT, 9):
                sel = (sel + 1) % len(items)
            elif key == curses.KEY_HOME:
                sel = 0
            elif key == curses.KEY_END:
                sel = len(items) - 1
            elif key in self.ENTER_KEYS:
                result = ("item", items[sel][2])
                break
            elif key == 27:
                result = None
                break
            elif 0 < key < 256:
                ch = chr(key)
                if ch in extra_keys:
                    result = ("key", ch)
                    break
                exact = [it for it in items if it[0] == ch]
                loose = [it for it in items if it[0].lower() == ch.lower()]
                hit = exact or (loose if len(loose) == 1 else [])
                if hit:
                    result = ("item", hit[0][2])
                    break
        del win
        self.scr.touchwin()
        return result

    def confirm(self, title: str, lines: list[str], yes: str = "", no: str = "") -> bool:
        """A yes/no question; No is preselected."""
        picked = self.choose(title, [("s", yes or tr("Sì"), True), ("n", no or tr("No"), False)],
                             header=lines, current=False)
        return picked == ("item", True)

    def production_menu(self, city) -> None:
        g = self.g
        keys = [k for k in list(UNIT_TYPES) + [WARHEAD, CHEMICAL, SATELLITE, ASAT]
                if g.can_build(city, k)]
        rate = g.production_rate(city)
        lines = []
        for k in keys:
            cost = production_cost(k)
            eta = "∞" if rate <= 0 else f"{-(-cost // rate):.0f}"
            if k in UNIT_TYPES:
                t = UNIT_TYPES[k]
                stats = tr("att {attack} dif {defense} PV {hp} mosse {moves}", attack=t.attack,
                           defense=t.defense, hp=t.hp, moves=t.move)
            elif k == SATELLITE:
                stats = tr("in orbita: vede una fascia del mondo")
            else:
                stats = tr("scorta strategica")
            lines.append(tr("{production:20s} costo {cost:3d}  {eta:>3s} turni  {stats}",
                            production=(self.glyph(k) + " " if k in UNIT_TYPES else "  ")
                            + word(PRODUCTION_NAMES[k]), cost=cost, eta=eta, stats=stats))
        items = [(k, line, k) for k, line in zip(keys, lines)]
        directive = g.factions[self.viewer].directive
        notes = []
        if directive and city.manual:
            items.append(("X", tr("torna alla direttiva: {directive}",
                                  directive=word(DIRECTIVES[directive]).split(" (")[0]), "X"))
        elif directive:
            notes = [tr("Scegliendo a mano, questa città non seguirà più la direttiva.")]
        picked = self.choose(tr("Produzione di {city} ({rate:.1f} punti/turno)", city=city.name, rate=rate),
                             items, notes=notes, current=city.production)
        if picked is None:
            return
        ch = picked[1]
        if ch == "X" and directive and city.manual:
            self.do({"op": "release", "city": city.id})
            self.status = tr("{city} torna a seguire la direttiva.", city=city.name)
            return
        if ch in keys and self.do({"op": "produce", "city": city.id, "key": ch}) == "ok":
            self.status = tr("{city} ora produce {production}.", city=city.name, production=PRODUCTION_NAMES[ch])

    DIRECTIVE_KEYS = {"0": "", "1": "auto", "2": "land", "3": "air", "4": "sea",
                      "5": "amphibious", "6": "defense", "7": "nuclear"}

    def directive_menu(self) -> None:
        """One order for every city: what the whole war economy builds."""
        fac = self.g.factions[self.viewer]
        items = [(key, word(DIRECTIVES[name]), name) for key, name in self.DIRECTIVE_KEYS.items()]
        manual = sum(1 for c in self.g.cities_of(self.viewer) if c.manual)
        notes = [tr("Le città che hai impostato a mano restano come sono.")]
        if manual:
            notes.append(tr("Città scelte a mano: {n}. Premi T per includere anche quelle.", n=manual))
        picked = self.choose(tr("Direttiva di produzione"), items,
                             header=[tr("Una direttiva cambia subito la produzione di tutte le città")],
                             notes=notes, current=fac.directive, extra_keys="Tt" if manual else "")
        if picked is None:
            return
        include_all = picked[0] == "key"
        if include_all:
            picked = self.choose(tr("Direttiva per TUTTE le città, anche quelle scelte a mano"),
                                 items, current=fac.directive)
            if picked is None:
                return
        name = picked[1]
        changed = self.do({"op": "directive", "name": name, "all": include_all})
        label = word(DIRECTIVES[name]).split(" (")[0]
        self.status = tr("Direttiva: {directive}. Città riconvertite: {n}.", directive=label, n=changed) if name else \
            tr("Produzione manuale: ogni città continua con quello che sta costruendo.")

    def cards_menu(self) -> None:
        """The hand: read your cards and play one."""
        g = self.g
        hand = g.factions[self.viewer].cards
        if not hand:
            self.dialog(tr("Carte"), [tr("Non hai carte."), "",
                                      tr("Ne peschi una a fine turno con una probabilità che cresce con le"),
                                      tr("città conquistate nel turno: 20% per una piccola, 60% per una grande"),
                                      tr("o una capitale, al massimo 80%;"),
                                      tr("e una ogni {every} turni dai servizi segreti (massimo {limit} in mano).",
                                         every=cards.BRIEFING_EVERY, limit=cards.HAND_LIMIT)])
            return
        letters = "abcde"
        items = []
        for k, key in enumerate(hand):
            c = cards.CARDS[key]
            odds = " · " + tr("riesce nel {pct}% dei casi", pct=int(c.chance * 100)) if c.chance < 1 else ""
            items.append((letters[k], [f"♠ {word(c.name)}{odds}", word(c.text)], k))
        playing = self.my_turn()
        picked = self.choose(tr("Le tue carte ({n}/{limit})", n=len(hand), limit=cards.HAND_LIMIT), items,
                             notes=[] if playing else [tr("Le carte si giocano nel tuo turno.")])
        if picked is None or not playing:
            return
        card = cards.CARDS[hand[picked[1]]]
        if card.target == "none":
            self.play_card(card.key)
        elif card.target == "faction":
            rivals = [f for f in g.factions if f.alive and f.idx != self.viewer]
            picked = self.choose(tr("♠ {card}: su quale fazione?", card=card.name),
                                 [(str(k + 1), word(f.name), f.idx) for k, f in enumerate(rivals)])
            if picked is not None:
                self.play_card(card.key, target=picked[1])
        else:
            self.pending_card = card.key
            self.mode = "card"
            hint = {"own_city": N("♠ {card}: porta il cursore su una tua città e premi Invio."),
                    "enemy_unit": N("♠ {card}: porta il cursore su un'unità nemica fuori dalle città e premi Invio."),
                    "enemy_city": N("♠ {card}: porta il cursore su una città nemica e premi Invio."),
                    "neutral_city": N("♠ {card}: porta il cursore su una città neutrale e premi Invio.")
                    }[card.target]
            self.status = tr(hint, card=card.name)

    def play_card(self, key: str, cell: int | None = None, target: int | None = None) -> None:
        result = self.do({"op": "card", "card": key, "cell": cell, "target": target})
        name = cards.CARDS[key].name
        if result == "ok":
            self.audio.sfx("spy" if key == "spy" else "card")
            self.status = tr("♠ {card}: fatto!", card=name)
            if key == "spy":
                report = [e.shown().lstrip("◈ ") for e in self.g.events if intel_line(e)][-6:]
                self.dialog(tr("◈ RAPPORTO DEI SERVIZI SEGRETI"), report)
        elif result == "failed":
            self.audio.sfx("loss")
            self.status = tr("♠ {card}: il tentativo è fallito, la carta è persa.", card=name)
        else:
            self.status = tr("♠ {card}: {reason} La carta resta in mano.", card=name,
                             reason=describe(result) or tr("non si può giocare così."))
        self.last_seq = max([self.last_seq] + [e.seq for e in self.g.events])

    def diplomacy_menu(self) -> None:
        g = self.g
        others = [f for f in g.factions if f.idx != self.viewer and f.alive]
        offers = g.proposals_to(self.viewer)
        lines = []
        for f in others:
            left = g.truce_left(self.viewer, f.idx)
            if left:
                state = tr("tregua ({turns} turni)", turns=left)
            elif f.idx in offers:
                state = tr("TI PROPONE UNA TREGUA")
            elif [self.viewer, f.idx] in g.proposals:
                state = tr("proposta inviata")
            else:
                state = tr("in guerra")
            lines.append(f"{word(f.name):24s} {state}")
        picked = self.choose(tr("Diplomazia"), [(str(k), line, f) for k, (line, f)
                                                in enumerate(zip(lines, others), 1)],
                             notes=[tr("Scegli una fazione per proporle una tregua o rispondere."),
                                    tr("Durante la tregua le due fazioni non possono attaccarsi.")])
        if picked is None:
            return
        f = picked[1]
        if f.idx in offers:
            accept = self.confirm(tr("Tregua"), [tr("{faction} propone una tregua di 15 turni.", faction=f.name),
                                                 tr("Accetti?")],
                                  tr("Accetto la tregua"), tr("Rifiuto"))
            result = self.do({"op": "truce_answer", "target": f.idx, "accept": accept})
        elif not g.truce_left(self.viewer, f.idx):
            result = self.do({"op": "truce", "target": f.idx})
        else:
            return
        self.status = describe(result) or self.status

    def music_menu(self) -> None:
        """Choose the background music and mute or unmute the effects."""
        a = self.audio
        items = [(key, word(music_name(choice)), choice) for key, choice in music_keys().items()]
        items.append(("e", tr("effetti sonori: attivi (premi per spegnerli)") if a.effects
                      else tr("effetti sonori: muti (premi per accenderli)"), "effects"))
        picked = self.choose(tr("Audio: musica ed effetti"), items, current=a.music_choice)
        if picked is None:
            return
        if picked[1] == "effects":
            on = a.toggle_effects()
            self.status = tr("Effetti sonori: attivi.") if on else tr("Effetti sonori: muti.")
            return
        a.select_music(picked[1])
        if a.available:
            self.status = tr("Musica: {music}.", music=music_name(picked[1]))
        else:
            self.status = tr("Musica: {music} (nessun lettore audio trovato: solo il beep).",
                             music=music_name(picked[1]))

    def language_menu(self) -> None:
        """Choose the language of the interface; it changes at once."""
        picked = self.choose("Lingua / Language", [(str(k), name, code) for k, (code, name)
                                                   in enumerate(i18n.LANGS.items(), 1)],
                             current=i18n.language())
        if picked is None:
            return
        i18n.save_language(i18n.set_language(picked[1]))
        self.status = tr("Lingua: {language}.", language=i18n.LANGS[i18n.language()])

    def chat(self) -> None:
        text = self.ask(tr("Messaggio"), [tr("Scrivi un messaggio per tutti i giocatori.")], "> ", 120)
        if text:
            self.do({"op": "chat", "text": text})

    # ----------------------------------------------------------- orders
    def do(self, cmd: dict) -> str:
        """Send one command through the session (local game or server)."""
        result = self.session.do(self.viewer, cmd, progress=self._progress)
        if result == "disconnected":
            self.status = tr("Connessione con il server perduta.")
        self.sync()
        return result

    def _progress(self, who: str) -> None:
        self.status = tr("⌛ {faction} sta muovendo...", faction=who)
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
        first = self.turn_key is None
        self.turn_key = key
        if g.realtime and not first:
            self.pulse()
            return
        if not self.session.online and g.faction.human and not g.realtime:
            self.viewer = g.current
        if self.my_turn():
            self.start_human_turn()
        else:
            self.active = None
            if self.session.started:
                self.status = tr("⌛ Tocca a {faction}: aspetta il tuo turno.", faction=g.faction.name)

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
            self.status = tr("Tutte le unità hanno ricevuto ordini. Premi E per finire il turno.")

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
            self.status = tr("Nessuna unità selezionata (n per la prossima).")
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
            self.dialog(tr("Passaggio di consegne"), [tr("Tocca a: {faction}", faction=g.faction.name),
                                                      tr("Gli altri giocatori distolgano lo sguardo.")])
        reel = self.session.take_reel(self.viewer) if hasattr(self.session, "take_reel") else []
        if reel:
            self.last_reel = reel
            title = tr("BOLLETTINO DI GUERRA · {date} · turno {turn}", date=self.date_text(), turn=g.turn)
            self.bulletins.append((title, self.bulletin_text(reel), reel))
            del self.bulletins[:-30]
            self.play_bulletin(reel)
        self.announce_world_events()
        self.announce_mission()
        self.select_next()
        if self.active is None:
            self.cursor = self._home_cell()
            self.center()
        self.status = tr("Turno {turn}: ai tuoi ordini.", turn=g.turn)
        self.warned = False
        if hasattr(self.session, "start_clock"):
            self.session.start_clock()
        if self.session.online:
            self.audio.sfx("turn")

    def announce_mission(self) -> None:
        """The secret objective, shown once to each player at its first turn."""
        g = self.g
        shown = self.__dict__.setdefault("missions_shown", set())
        if self.viewer in shown or not g.factions[self.viewer].mission:
            return
        shown.add(self.viewer)
        self.audio.sfx("card")
        self.draw()
        self.dialog(tr("◎ IL TUO OBIETTIVO SEGRETO"), [
            missions.text(g, self.viewer), "",
            *textwrap.wrap(tr("Se lo completi vinci subito. Gli altri non lo conoscono, e tu non "
                              "conosci il loro (solo una carta Spionaggio lo rivela)."), 66),
            tr("Il pannello mostra a che punto sei; o lo rilegge in ogni momento.")])

    def announce_world_events(self) -> None:
        """World events since this player's last turn, one dialog each."""
        g = self.g
        seen = getattr(self, "world_seen", 0)
        fresh = [e for e in g.events if e.level == "world" and e.seq > seen and e.turn >= g.turn - 1]
        if g.events:
            self.world_seen = max(seen, max(e.seq for e in g.events))
        for e in fresh:
            name, _, rest = e.shown().partition(": ")
            self.audio.sfx("alert")
            self.draw()
            self.dialog("✦ " + name, textwrap.wrap(rest, 64))

    def space_menu(self) -> None:
        """Satellites in orbit and the anti-satellite weapons."""
        g = self.g
        if not g.scenario.modern:
            self.status = tr("In questo scenario non ci sono armi spaziali.")
            return
        fac = g.factions[self.viewer]
        header = [tr("Un satellite spia vede tutte le unità nemiche (tranne i sottomarini) in una "
                     "fascia larga 25° e mostra le loro mosse nel bollettino. Ogni turno sorvola "
                     "un'altra fascia. Si costruisce nelle città grandi o nelle capitali.")]
        header = [line for text in header for line in textwrap.wrap(text, 70)] + [""]
        if fac.satellites:
            for k, x in enumerate(fac.satellites):
                band = g.satellite_band(x)
                west = self.w.lonlat(band.start % self.w.width)[0]
                east = self.w.lonlat((band.stop - 1) % self.w.width)[0]
                header.append(tr("Satellite {n}: sorvola da {west} a {east}", n=k + 1,
                                 west=_longitude(west), east=_longitude(east)))
        else:
            header.append(tr("Nessun satellite in orbita."))
        header.append(tr("Armi antisatellite pronte: {n}", n=fac.asats))
        items = []
        for o in g.factions:
            if o.idx == self.viewer or not o.alive:
                continue
            items.append((str(len(items) + 1),
                          tr("Lancia un'arma antisatellite contro {faction} ({n} satelliti)",
                             faction=o.name, n=len(o.satellites)), o.idx))
        picked = self.choose(tr("Spazio"), items, header=header) if items else None
        if picked is None:
            return
        result = self.do({"op": "asat", "target": picked[1]})
        self.status = describe(result) or tr("Satellite nemico abbattuto!")

    def objectives(self) -> None:
        """Secret objective, regions and world events on one page."""
        g = self.g
        if getattr(self, "tutorial", None) is not None:
            self.tutorial.seen_objectives = True
        me = self.viewer
        lines = []
        if g.factions[me].mission.get("kind") in ("regions", "eliminate", "cities", "capitals"):
            lines += [tr("◎ OBIETTIVO SEGRETO"), "  " + missions.text(g, me),
                      "  " + tr("A che punto sei: {progress}", progress=missions.progress(g, me)),
                      "  " + tr("Chi completa il suo obiettivo vince subito."), ""]
        lines += [tr("⚑ REGIONI: chi ne tiene tutte le città ha un bonus di produzione in tutto l'impero"), ""]
        mine = {k: (n, t) for k, n, t in regions.progress(g, me)}
        width = max(len(word(r.name)) for r in regions.REGIONS.values())
        for key, region in regions.REGIONS.items():
            n, t = mine.get(key, (0, len(regions.cities_in(g, key))))
            owner = g.region_holders.get(key)
            who = f"  ← {word(g.factions[owner].name)}" if owner is not None else ""
            lines.append(f"  {word(region.name):{width}s} {n:3d}/{t:<3d} +{int(regions.bonus_of(g, key) * 100):2d}%{who}")
        lines += ["", tr("✦ EVENTI MONDIALI (uno ogni 5-8 turni)")]
        active = events.describe_active(g)
        lines += ["  " + tr("In corso: {effects}", effects=", ".join(active))] if active \
            else ["  " + tr("Nessun effetto in corso.")]
        for e in [e for e in g.events if e.level == "world"][-5:]:
            lines += textwrap.wrap(f"[{e.turn}] {e.shown()}", 76, initial_indent="  ", subsequent_indent="    ")
        self.pager(tr("Obiettivo, regioni ed eventi mondiali"), lines, tr("↑↓ scorri · un tasto chiude"))

    def pulse(self) -> None:
        """Real time: a pulse came. No animation (there is one every few
        seconds): the bulletin goes to the archive (B), world events are
        announced, and the orders go on."""
        g = self.g
        reel = self.session.take_reel(self.viewer) if hasattr(self.session, "take_reel") else []
        if reel:
            self.last_reel = reel
            title = tr("BOLLETTINO DI GUERRA · {date} · turno {turn}", date=self.date_text(), turn=g.turn)
            self.bulletins.append((title, self.bulletin_text(reel), reel))
            del self.bulletins[:-30]
        self.announce_world_events()
        if self.active is None or self.active.id not in g.units:
            self.select_next()
        self.warned = False

    def end_human_turn(self) -> None:
        self.active = None
        g = self.g
        if g.events:  # the newsreel will ring every event; quiet the summary
            self.last_seq = max(self.last_seq, max(e.seq for e in g.events))
        self.do({"op": "end_turn"})

    # ------------------------------------------------------- newsreel
    def _focus(self, cell: int) -> None:
        """Pan the map so ``cell`` is in view (keep the view if it already is)."""
        mw, mh = self.view_size()
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
                    self.status = tr("▶ Bollettino: {who} in movimento", who=self._who(act))
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
                    who, city = self._faction(act.get("new")), act.get("name", "")
                    self.status = tr("▶ {faction} conquista {city} — LA PERDIAMO!", faction=who, city=city) \
                        if lost else tr("▶ {faction} conquista {city}", faction=who, city=city)
                    if lost:
                        self.audio.sfx("loss", force=True)
                elif op == "fall":
                    self.status = tr("▶ {faction} è caduta!", faction=self._faction(act.get("old")))
                    self.audio.sfx("fall", force=True)
                elif op == "nuke":
                    self.fx = {c: ("☢", "fallout", curses.A_REVERSE) for c in self.w.ring(cell, 1)}
                    self.status = tr("▶ ☢ Attacco nucleare su {place}", place=act.get("name", ""))
                    self.audio.sfx("nuke", force=True)
                elif op == "card":
                    self.fx = {cell: ("♠", "magenta", curses.A_REVERSE)}
                    self.status = f"▶ {self.scene_line(act)}"
                    self.audio.sfx("card", force=act.get("victim") == self.viewer)
                elif op == "chem":
                    self.fx = {c: ("☣", "green", 0) for c in self.w.ring(cell, 1)}
                    self.status = tr("▶ ☣ Armi chimiche su {place}", place=act.get("name", ""))
                    self.audio.sfx("gas", force=True)
                self.draw()
                time.sleep(self.REEL_PACE.get(op, 0.2))
        finally:
            self.scr.timeout(BLINK_MS)   # back to the main loop's pace, not to blocking reads
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
        name = UNIT_TYPES[kind].name if kind in UNIT_TYPES else N("unità")
        return f"{word(name)} ({word(self._faction(act.get('owner')))})"

    def _centre(self, cell: int) -> None:
        mw, mh = self.view_size()
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
        tname = lower_noun(word(UNIT_TYPES[tgt].name)) if tgt in UNIT_TYPES else tr("la città")
        head = N("⚔ ATTACCO CONTRO DI NOI: {who} attacca {target} ({defender})") if on_us else \
            N("⚔ Scontro: {who} attacca {target} ({defender})")
        self.status = tr(head, who=self._who(act), target=tname, defender=self._faction(act.get("defender")))
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
            outcome = tr("l'attaccante è distrutto — la difesa tiene!") if on_us else \
                tr("l'attaccante è distrutto")
        elif result == "captured":
            self.fx = {target: ("⚑", colour, curses.A_REVERSE)}
            outcome = tr("la città cade")
        else:
            self.fx = {target: ("✕", "alert", curses.A_REVERSE)}
            outcome = tr("il bersaglio è distrutto") if tgt else tr("le difese della città crollano")
            if on_us:
                self.audio.sfx("loss")
        self.status += f" → {outcome}"
        self.draw()
        time.sleep(0.45 * slow)
        return self._skip_key()

    # ------------------------------------------------- written bulletin
    def _place(self, cell: int, bare: bool = False) -> str:
        """'a Vilnius', 'presso Vilnius' or coordinates, for the chronicle
        (``bare``: only the name of the place)."""
        g = self.g
        city = g.city(cell)
        if city is not None:
            return city.name if bare else tr("a {place}", place=city.name)
        near = min(g.cities, key=lambda c: self.w.dist(c.cell, cell))
        if self.w.dist(near.cell, cell) <= 4:
            return near.name if bare else tr("presso {place}", place=near.name)
        lon, lat = self.w.lonlat(cell)
        where = f"{abs(lat):.0f}°{'N' if lat >= 0 else 'S'} {abs(lon):.0f}°{'E' if lon >= 0 else 'W'}"
        return where if bare else tr("a {place}", place=where)

    def scene_line(self, act: dict) -> str:
        """One line of chronicle for a bulletin scene (moves have none)."""
        me = self.viewer
        op = act["op"]
        if op == "attack":
            kind = act.get("glyph", "")
            who = UNIT_TYPES[kind].name if kind in UNIT_TYPES else N("Unità")
            tgt = act.get("target") or ""
            result = act.get("result")
            city = self.g.city(act["cell"])
            if tgt in UNIT_TYPES:
                where = tr("su {unit} {place}", unit=UNIT_TYPES[tgt].name, place=self._place(act["cell"]))
            else:
                where = tr("sulla città di {city}", city=city.name) if city else self._place(act["cell"])
            if act.get("defender") == me:
                outcome = {"lost": N("RESPINTO"), "captured": N("LA CITTÀ CADE")}.get(
                    result, N("PERDIAMO l'unità") if tgt in UNIT_TYPES else N("difese a terra"))
                return tr("⚔ CONTRO DI NOI · {unit} ({attacker}) {where} → {outcome}", unit=who,
                          attacker=self._faction(act.get("attacker")), where=where, outcome=outcome)
            outcome = {"lost": N("fallisce"), "captured": N("la città cade")}.get(result, N("bersaglio distrutto"))
            return tr("⚔ {unit} ({attacker}) {where} ({defender}) → {outcome}", unit=who,
                      attacker=self._faction(act.get("attacker")), where=where,
                      defender=self._faction(act.get("defender")), outcome=outcome)
        if op == "capture":
            params = dict(city=act.get("name", "?"), new=self._faction(act.get("new")),
                          old=self._faction(act.get("old")))
            if act.get("old") == me:
                return tr("⚑ {city} conquistata da {new} (prima: {old}) — PERSA", **params)
            return tr("⚑ {city} conquistata da {new} (prima: {old})", **params)
        if op == "fall":
            return tr("✖ {faction} ha perso l'ultima città: è fuori dalla guerra",
                      faction=self._faction(act.get("old")))
        if op == "nuke":
            return tr("☢ {faction} colpisce {place} con un'arma nucleare",
                      faction=self._faction(act.get("actor")), place=act.get("name", "?"))
        if op == "chem":
            return tr("☣ {faction} usa armi chimiche su {place}",
                      faction=self._faction(act.get("actor")), place=act.get("name", "?"))
        if op == "card":
            params = dict(faction=self._faction(act.get("actor")), card=act.get("name", "?"),
                          text=act.get("text", ""))
            if act.get("victim") == me:
                return tr("♠ {faction} gioca «{card}»: {text} — CONTRO DI NOI", **params)
            return tr("♠ {faction} gioca «{card}»: {text}", **params)
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
        played = [a for a in reel if a["op"] == "card"]
        moves: dict[int, dict] = {}
        for a in reel:
            if a["op"] == "move":
                moves[a["unit"]] = a          # last seen position of each unit
        out: list[str] = []
        if wmd:
            out += [tr("ARMI DI DISTRUZIONE DI MASSA")] + [self.scene_line(a) for a in wmd] + [""]
        if played:
            out += [tr("CARTE E COLPI DI MANO")] + [self.scene_line(a) for a in played] + [""]
        if on_us:
            held = sum(1 for a in on_us if a.get("result") == "lost")
            out.append(tr("IL NOSTRO FRONTE · {attacks} attacchi subiti, {held} respinti",
                          attacks=len(on_us), held=held))
            out += [self.scene_line(a) for a in on_us] + [""]
        if cities:
            lost = sum(1 for a in cities if a["op"] == "capture" and a.get("old") == me)
            out.append(tr("CITTÀ CHE HANNO CAMBIATO BANDIERA · ne perdiamo {n}", n=lost) if lost
                       else tr("CITTÀ CHE HANNO CAMBIATO BANDIERA"))
            out += [self.scene_line(a) for a in cities] + [""]
        if others:
            out.append(tr("ALTRI SCONTRI AVVISTATI · {n}", n=len(others)))
            out += [self.scene_line(a) for a in others] + [""]
        if moves:
            by_kind = Counter(UNIT_TYPES[a["glyph"]].name for a in moves.values() if a["glyph"] in UNIT_TYPES)
            by_side = Counter(self._faction(a["owner"]) for a in moves.values())
            out.append(tr("MOVIMENTI OSSERVATI · {n} unità", n=len(moves)))
            out.append("  " + ", ".join(f"{n} {lower_noun(word(k))}" for k, n in by_kind.most_common()))
            out.append("  " + ", ".join(f"{word(side)}: {n}" for side, n in by_side.most_common()))
            near = Counter(self._place(a["cell"], bare=True) for a in moves.values()).most_common(3)
            out.append("  " + tr("Zone più attive: {places}", places=", ".join(f"{p} ({n})" for p, n in near)))
        return out or [tr("Nessuna novità di rilievo sul fronte.")]

    def read_bulletins(self, index: int | None) -> None:
        """Read the written bulletins: ←/→ older and newer turns, ↑/↓ scroll,
        R replays the animation, any other key closes."""
        if index is None or not self.bulletins:
            self.status = tr("Nessun bollettino ancora: arriverà a fine turno.")
            return
        while True:
            title, lines, reel = self.bulletins[index]
            nav = f"{index + 1}/{len(self.bulletins)}"
            key = self.pager(f"{title} ({nav})", lines,
                             tr("↑↓ scorri · ←→ turni precedenti/successivi · R rivedi l'animazione · Esc chiudi"))
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
                    attr = curses.A_BOLD if line.isupper() or loud(line) else 0
                    win.addstr(2 + k, 2, line[: width - 4], attr)
                more = "▼" if top + body < len(lines) else " "
                win.addstr(height - 1, 2, f" {footer} {more} "[: width - 4], curses.A_DIM)
            except curses.error:
                pass
            win.refresh()
            key = self.read_key(win)
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
            lines = [tr("Gli arsenali si sono svuotati in pochi minuti."),
                     tr("Le città del mondo sono in fiamme; l'inverno nucleare scende."),
                     "", tr("NESSUNO HA VINTO."), "",
                     tr("« Strano gioco. L'unica mossa vincente è non giocare. »")]
            title = tr("MEZZANOTTE")
        else:
            fac = g.factions[winner]
            if self.session.online:
                human_won = winner == self.viewer
            else:
                human_won = fac.human
            why = {"conquest": N("{faction} ha sconfitto tutti i rivali."),
                   "domination": N("{faction} domina il mondo."),
                   "turns": N("{faction} vince ai punti allo scadere."),
                   "mission": N("{faction} ha completato il suo obiettivo segreto.")}[reason]
            lines = [tr(why, faction=fac.name), "",
                     tr("VITTORIA!") if human_won else tr("SCONFITTA."), ""]
            if any(f.mission.get("kind") in ("regions", "eliminate", "cities", "capitals") for f in g.factions):
                lines += [tr("Gli obiettivi segreti erano:")]
                lines += [f"  {word(f.name)}: {missions.text(g, f.idx)}" for f in g.factions if f.mission]
                lines.append("")
            if g.scenario.key == "tutorial" and human_won:
                lines = [tr("Tirana è caduta: la Repubblica Ribelle è sconfitta."), "",
                         tr("TUTORIAL COMPLETATO! Sei pronto per la guerra vera:"),
                         tr("prova la Guerra Fredda 1985 o la Terza Guerra Mondiale."), ""]
            for f in sorted(g.factions, key=g.score, reverse=True):
                lines.append(tr("{faction:24s} punti {score:5d}  città {cities:3d}  armi DM usate {wmd}",
                                faction=f.name, score=g.score(f), cities=len(g.cities_of(f.idx)), wmd=f.used_wmd))
            title = tr("FINE DELLA GUERRA")
        self.dialog(title, lines, tr("premi un tasto per uscire"))
        self.quit = True

    # ----------------------------------------------------------- input
    VIEW_KEYS = {ord("m"), ord("M"), ord("r"), ord("?"), ord("Q"), ord("T"), ord("n"), ord("B"),
                 ord("K"), ord("h"), 9, ord("+"), ord("="), ord("-"), ord("o"), ord("L"), ord("Z"), ord("V")}

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
        if self.mode in ("goto", "nuke", "chem", "card"):
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
        if key in (ord("+"), ord("=")):
            self.set_zoom(1)
            return
        if key == ord("-"):
            self.set_zoom(-1)
            return
        if not self.my_turn() and key not in self.VIEW_KEYS and key != -1:
            if not self.session.started:
                self.status = tr("In attesa che arrivino tutti i giocatori...")
            elif not g.over:
                self.status = tr("Attendi il tuo turno: ora tocca a {faction}.", faction=g.faction.name)
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
                self.status = tr("Solo le unità di terra possono fortificarsi.")
        elif key == ord("A") and self.active:
            self.order("auto")
            self.status = tr("Unità affidata all'IA (Invio sull'unità per riprenderla).")
        elif key == ord("P"):
            self.directive_menu()
        elif key == ord("g") and self.active:
            self.mode = "goto"
        elif key == ord("v"):
            woke = self.do({"op": "wake", "cell": self.cursor})
            self.status = tr("{n} unità sveglie.", n=woke)
            self.skipped.clear()
        elif key == ord("l") and self.active:
            n = self.do({"op": "load", "unit": self.active.id})
            self.status = tr("Caricate {n} unità.", n=n) if n not in ("0", "illegal") else \
                tr("Niente da caricare (serve una nave in città).")
        elif key == ord("u") and self.active:
            n = self.do({"op": "unload", "unit": self.active.id})
            self.status = tr("Scaricate {n} unità.", n=n) if n not in ("0", "illegal") else \
                tr("Si scarica solo in città.")
        elif key == ord("p"):
            city = g.city(self.cursor)
            if city is not None and city.owner == self.viewer:
                self.production_menu(city)
            else:
                self.status = tr("Metti il cursore su una tua città.")
        elif key == ord("D") and self.active:
            if self.confirm(tr("Congedo"), [tr("Congedare {unit}?", unit=self.active.type.name)]):
                self.do({"op": "disband", "unit": self.active.id})
                self.active = None
                self.select_next()
        elif key == ord("O"):
            self.diplomacy_menu()
        elif key == ord("K"):
            self.cards_menu()
        elif key == ord("Z"):
            self.space_menu()
        elif key == ord("V"):
            self.toggle_symbols()
        elif key == ord("o"):
            self.objectives()
        elif key == ord("h") and self.tutorial is not None:
            self.tutorial.visible = not self.tutorial.visible
        elif key == ord("B"):
            self.read_bulletins(len(self.bulletins) - 1 if self.bulletins else None)
        elif key == ord("T"):
            if self.session.online:
                self.chat()
            else:
                self.status = tr("La chat serve nelle partite online.")
        elif key == ord("m"):
            self.mode = "overview"
        elif key == ord("M"):
            self.music_menu()
        elif key == ord("L"):
            self.language_menu()
        elif key == ord("r"):
            self.center()
        elif key == ord("N"):
            if g.factions[self.viewer].warheads <= 0:
                self.status = tr("Nessuna testata nucleare disponibile.")
            else:
                self.mode = "nuke"
        elif key == ord("C"):
            if g.factions[self.viewer].chemicals <= 0:
                self.status = tr("Nessuna arma chimica disponibile.")
            else:
                self.mode = "chem"
        elif key == ord("E"):
            self.end_human_turn()
        elif key == ord("S"):
            self.save()
        elif key == ord("Q"):
            note = tr("Il server tiene la partita: potrai rientrare.") if self.session.online \
                else tr("La partita verrà salvata.")
            if self.confirm(tr("Uscire?"), [note], tr("Esci"), tr("Resta")):
                if not self.session.online:
                    self.save()
                self.quit = True
        elif key == ord("?"):
            self.dialog(tr("Comandi"), tr(HELP).splitlines())

    def move_cursor(self, dx: int, dy: int) -> None:
        x, y = self.w.xy(self.cursor)
        y = max(0, min(self.w.height - 1, y + dy))
        self.cursor = self.w.idx(x + dx, y)
        self.follow_cursor()

    def take_command(self, u: Unit) -> None:
        """Clicked in the panel: this unit becomes the active one."""
        if u.id not in self.g.units or not self.my_turn():
            return
        self.skipped.discard(u.id)
        self.select(u)
        if u.order in ("sentry", "fortify", "auto"):
            self.do({"op": "order", "unit": u.id, "order": None})

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
        if mode == "card":
            key, self.pending_card = self.pending_card, None
            if key:
                self.play_card(key, cell=self.cursor)
            return
        if mode == "goto":
            a = self.active
            if a is not None:
                result = self.order("goto", target=self.cursor)
                tutorial = getattr(self, "tutorial", None)
                if result == "ok" and tutorial is not None:
                    tutorial.goto_given = True
                if result != "ok":
                    self.status = describe(result)
                    if self.active is not None:
                        self.cursor = self.active.cell
            return
        city = g.city(self.cursor)
        place = city.name if city else tr("la casella selezionata")
        if mode == "chem":
            if not g.can_chemical(self.viewer, self.cursor):
                self.status = tr("Bersaglio fuori portata (max {cells} caselle dalle tue forze).", cells=CHEM_RANGE)
                return
            if self.confirm(tr("☣ Armi chimiche"), [tr("Colpire {place} con gas nervino?", place=place),
                                                    tr("Orologio dell'Apocalisse: -1 minuto.")],
                            tr("Lancia il gas"), tr("Annulla")):
                self.status = describe(self.do({"op": "chem", "cell": self.cursor}))
        else:
            if city is not None and city.owner == self.viewer:
                self.status = tr("Non puoi colpire una tua città.")
                return
            code = f"{random.randint(0, 9999):04d}"
            lines = [tr("Bersaglio: {place}", place=place),
                     tr("Testate disponibili: {n}", n=g.factions[self.viewer].warheads),
                     tr("Orologio dell'Apocalisse: {minutes} minuti (-2/-3 dopo il lancio)", minutes=g.doomsday),
                     tr("Il nemico potrebbe rispondere con tutto il suo arsenale."), "",
                     tr("CODICE DI AUTORIZZAZIONE: {code}", code=code)]
            if self.ask(tr("☢ AUTORIZZAZIONE AL LANCIO"), lines, tr("Digita il codice (Invio):"), 4) == code:
                self.status = describe(self.do({"op": "nuke", "cell": self.cursor}))
            else:
                self.status = tr("Codice errato: lancio annullato.")
        if self.active is not None:
            self.after_action()

    def mouse(self) -> None:
        """The mouse. Left click: on one of your units selects it;
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
        motion = getattr(curses, "REPORT_MOUSE_POSITION", 0)
        up = state & (curses.BUTTON1_RELEASED | curses.BUTTON1_CLICKED)
        if self._pan is not None and state & wheel_up and not up:
            # old ncurses (no SGR mouse) reads a drag motion as "wheel up"
            state = motion
        elif (state & wheel_up or state & wheel_down) and state & getattr(curses, "BUTTON_CTRL", 0):
            # Ctrl+wheel, or a pinch on a touch screen: zoom around that point
            self.set_zoom(1 if state & wheel_up else -1, (mx, my) if inside else None)
            return
        elif state & wheel_up or state & wheel_down:
            rows = self.view_size()[1]
            self.view_y = max(0, min(self.view_y + (-3 if state & wheel_up else 3),
                                     max(0, self.w.height - rows)))
            return
        if up and self._pan is None:
            action = self.hotspot(mx, my)
            if action is not None:      # a label of the panel or of the hints
                self.press(action)
                return
        if self.mode == "overview":
            if up and inside:
                kx, ky, _, _ = getattr(self, "overview_geom", (2, 2, 0, 0))
                y = min(self.w.height - 1, (my - 1) * 4 * ky + 2 * ky)
                self.cursor = self.w.idx(mx * 2 * kx + kx, y)
                self.mode = "normal"
                self.center()
            return
        pressed = state & curses.BUTTON1_PRESSED
        # Motion is reported only with a button held (mode 1002): if the press
        # got lost in a burst of events, the first motion starts the drag.
        if (pressed or state & motion and not state & curses.BUTTON1_RELEASED) \
                and inside and self._pan is None:
            self._pan = (mx, my)
            self._pan_view = (self.view_x, self.view_y)
            self._dragged = False
            return
        if self._pan is not None and not state & (curses.BUTTON1_RELEASED | curses.BUTTON1_CLICKED):
            px, py = self._pan
            # a wobble of one cell is still a click; more than that drags
            if inside and (getattr(self, "_dragged", False) or max(abs(mx - px), abs(my - py)) > 1):
                self._dragged = True
                self._pan_by(mx - px, my - py)
            return
        if state & (curses.BUTTON1_RELEASED | curses.BUTTON1_CLICKED):
            was_pressed = self._pan is not None
            dragged = was_pressed and getattr(self, "_dragged", False)
            if self._pan is not None and not dragged and inside:
                # No motion reports came (old terminal, or a burst over the
                # network): a release far from the press is still a drag.
                px, py = self._pan
                if max(abs(mx - px), abs(my - py)) > 1:
                    self._pan_by(mx - px, my - py)
                    dragged = True
            self._pan = self._pan_view = None
            self._dragged = False
            if dragged:
                cell = self._cell_at(mx, my) if inside else None
                if cell is not None:
                    self.cursor = cell   # the cursor lands where the hand let go
            elif inside and (was_pressed or state & curses.BUTTON1_CLICKED):
                self.click(self._cell_at(mx, my))
            return
        if state & (curses.BUTTON3_PRESSED | curses.BUTTON3_CLICKED) and inside:
            cell = self._cell_at(mx, my)
            if cell is not None:
                self.cursor = cell
                if self.mode == "normal" and self.my_turn():
                    self.select_at_cursor()

    def _pan_by(self, dx: int, dy: int) -> None:
        """The map follows the hand: the view moves ``dx``, ``dy`` characters
        back from where the drag started."""
        zx, zy = self.zoom_factor()
        base_x, base_y = self._pan_view
        rows = self.view_size()[1]
        self.view_x = (base_x - int(dx / zx)) % self.w.width
        self.view_y = max(0, min(base_y - int(dy / zy), max(0, self.w.height - rows)))

    @staticmethod
    def _terminal(data: bytes) -> None:
        """Send a control sequence straight to the terminal."""
        import os
        try:
            os.write(1, data)
        except OSError:
            pass

    def _cell_at(self, mx: int, my: int) -> int | None:
        zx, zy = self.zoom_factor()
        y = self.view_y + (my - 1) // zy
        if y >= self.w.height:
            return None
        return self.w.idx(self.view_x + mx // zx, y)

    def click(self, cell: int | None) -> None:
        if cell is None:
            return
        g = self.g
        if self.mode in ("goto", "nuke", "chem", "card"):
            if cell == self.cursor:
                self.confirm_target()        # second click on the target: go
            else:
                self.cursor = cell
                self.status = tr("Clicca di nuovo sulla stessa casella per confermare.")
            return
        self.cursor = cell
        if not self.my_turn():
            return
        a = self.active
        mine = [u for u in g.units_at(cell) if u.owner == self.viewer]
        # next to the active unit, a cell it can enter (own city, a plane over
        # a tank, a transport to board) is a move, not a change of unit
        enter = a is not None and cell in self.w.neighbors[a.cell] and g.classify(a, cell) is not None
        if mine and (a is None or cell != a.cell) and not enter:
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
            self.status = tr("Destinazione irraggiungibile per questa unità.")
            return
        self.mode = "goto"                   # show the route; a second click sends it
        self.status = tr("Percorso mostrato: clicca di nuovo sulla casella per partire (Esc annulla).")

    def save(self) -> None:
        result = self.session.do(self.viewer, {"op": "save"})
        if self.session.online:
            self.status = tr("Partita salvata sul server.") if result == "saved" else \
                tr("Il server non salva questa partita.")
        else:
            self.status = tr("Partita salvata in {path}", path=str(self.session.save_path))

    # ----------------------------------------------------------- loop
    def run(self) -> None:
        try:
            self._run()
        finally:
            self._terminal(b"\x1b[?1002l")

    def _run(self) -> None:
        if self.session.online:
            self.scr.timeout(300)
            if not self.lobby():
                return
        else:
            self.session.start(self._progress)
        # wake up a few times a second: the active unit blinks and the turn
        # timer ticks
        self.scr.timeout(BLINK_MS)
        self.sync()
        self.center()
        if self.g.scenario.key == "tutorial" and not self.session.online and not self.g.over:
            self.tutorial = Tutorial(self)
            self.tutorial.start()
        while not self.quit:
            self.draw()
            # whatever a dialog or the bulletin did to the input, keep waking
            # up: the active unit blinks and the turn timer ticks
            self.scr.timeout(BLINK_MS)
            key = self.scr.getch()
            self.tick_clock()
            if self.session.poll():
                self.sync()
            if self.tutorial is not None and key != -1:
                self.handle(key)
                key = -1
                if not self.quit:
                    self.tutorial.update()
            if self.session.closed and not self.quit:
                self.dialog(tr("Connessione persa"), [self.session.error or tr("Il server non risponde."),
                                                      tr("Rilancia con --join per rientrare.")])
                return
            if key != -1:
                self.handle(key)

    def tick_clock(self) -> None:
        """Turn timer: a warning near the end, then the turn ends by itself.
        Online the server keeps the time; here only the warning plays."""
        left = self.session.seconds_left()
        if left is None or not self.my_turn() or self.g.realtime:
            return                      # in real time the pulses come by themselves
        if left <= 10 and not getattr(self, "warned", False):
            self.warned = True
            self.audio.sfx("alert")
            self.status = tr("⏱ Restano {seconds} secondi!", seconds=left)
        if left == 0 and not self.session.online and self.mode in ("normal", "overview"):
            self.mode = "normal"
            self.status = tr("⏱ Tempo scaduto: turno finito.")
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
            lines = [tr("THE EMPIRE · partita online · {scenario}", scenario=g.scenario.name), "",
                     tr("Server: {address}", address=str(self.session.address)),
                     tr("Tu giochi con: {faction}", faction=g.factions[self.viewer].name), "",
                     tr("Posti:")]
            for seat in self.session.lobby:
                who = seat["name"] if seat["taken"] else tr("— libero —")
                state = "" if not seat["taken"] else (" ●" if seat["online"] else " " + tr("(offline)"))
                lines.append(f"  {word(g.factions[seat['faction']].name):24s} {who}{state}")
            ai = [word(f.name) for f in g.factions if not f.human]
            if ai:
                lines += ["", tr("Guidati dall'IA: {factions}", factions=", ".join(ai))]
            lines += ["", tr("In attesa degli altri giocatori...  (Q per uscire)")]
            for k, line in enumerate(lines):
                self.put(2 + k, 4, line, curses.A_BOLD if k == 0 else 0)
            self.scr.refresh()
            self.audio.music("menu")
            key = self.scr.getch()
            if key in (ord("Q"), ord("q")):
                return False
            if key == ord("M"):
                self.music_menu()
            elif key == ord("L"):
                self.language_menu()
        return True


SOUND_PRIORITY = ("nuke", "fall", "capture", "loss", "intercept", "gas", "crash", "asat",
                  "satellite", "card", "spy", "truce", "alert", "battle")


def _names(e) -> list[str]:
    """The words of an event that can name a faction: the parameters of its
    message (whatever the language), else its text."""
    if not e.msg:
        return [e.text]
    out = []
    for v in e.msg[1].values():
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list) and len(v) == 2 and isinstance(v[1], dict):
            out += [w for w in v[1].values() if isinstance(w, str)]
    return out


def intel_line(e) -> bool:
    """A line of a spy report (it starts with ◈ in every language)."""
    return (e.msg[0] if e.msg else e.text).startswith("◈")


# Words that make a line of the bulletin stand out (bold).
LOUD = (N("NOI"), N("PERSA"))


def loud(line: str) -> bool:
    return any(w in line or tr(w) in line for w in LOUD)


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
            elif (me in _names(e)) if e.msg else f"(prima: {me})" in e.text:
                heard.add("loss")      # the conqueror is someone else: we were the old owner
        elif sound == "fall":
            heard.add("loss" if e.actor == viewer else "fall")
        elif sound == "truce" and not any(me in w for w in _names(e)):
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
            scr.addstr(h - 1, 2, tr("↑↓ scegli · Invio conferma · Esc indietro")[: w - 3], curses.A_DIM)
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


def language_menu(scr) -> None:
    """Choose the language of the interface (and remember it)."""
    codes = list(i18n.LANGS)
    k = menu(scr, "Lingua / Language", [(i18n.LANGS[c], "") for c in codes])
    if k is not None:
        i18n.save_language(i18n.set_language(codes[k]))


def setup_menu(scr) -> dict | None:
    while True:
        keys = list(SCENARIOS)
        k = menu(scr, tr("Scegli lo scenario"),
                 [(word(SCENARIOS[s].name), word(SCENARIOS[s].description)) for s in keys]
                 + [(tr("Carica la partita salvata"), str(SAVE_PATH)),
                    (tr("Ospita una partita online..."),
                     tr("configura un server: posti, IA, timer, web TUI, password")),
                    (tr("Lingua / Language"), i18n.LANGS[i18n.language()])])
        if k is None:
            return None
        if k == len(keys):
            return {"load": SAVE_PATH}
        if k == len(keys) + 1:
            return {"serve": True}
        if k == len(keys) + 2:
            language_menu(scr)
            continue                 # the menu is drawn again in the new language
        sc = SCENARIOS[keys[k]]
        if sc.key == "tutorial":
            return {"scenario": sc.key, "humans": (sc.factions[0].key,),
                    "difficulty": "facile", "turn_time": 0}
        f = menu(scr, tr("{scenario}: scegli la tua fazione", scenario=sc.name),
                 [(word(fd.name), _faction_blurb(fd)) for fd in sc.factions])
        if f is None:
            continue
        d = menu(scr, tr("Difficoltà"), [(tr("facile"), tr("IA con industria al 75%")),
                                         (tr("normale"), tr("IA alla pari")),
                                         (tr("difficile"), tr("IA con industria al 130%"))])
        if d is None:
            continue
        mode = menu(scr, tr("Modalità"), [
            (tr("A turni"), tr("ogni fazione muove a turno, come in un gioco da tavolo")),
            (tr("Tempo reale"), tr("tutti insieme, senza turni: ogni pochi secondi un impulso "
                                   "ricarica le mosse, le città producono e l'IA agisce"))])
        if mode is None:
            continue
        if mode == 1:
            pulses = (5, 10, 20)
            p = menu(scr, tr("Velocità del tempo reale"), [
                (tr("Veloce"), tr("un impulso ogni 5 secondi")),
                (tr("Normale"), tr("un impulso ogni 10 secondi")),
                (tr("Calma"), tr("un impulso ogni 20 secondi"))])
            if p is None:
                continue
            return {"scenario": sc.key, "humans": (sc.factions[f].key,),
                    "difficulty": ("facile", "normale", "difficile")[d], "turn_time": 0,
                    "realtime": pulses[p]}
        times = (0, 60, 120, 180, 300)
        t = menu(scr, tr("Tempo per turno"), [
            (tr("Nessun limite"), tr("pensa quanto vuoi")),
            (tr("1 minuto"), tr("guerra lampo: decisioni di istinto")),
            (tr("2 minuti"), tr("ritmo serrato")),
            (tr("3 minuti"), tr("il giusto equilibrio")),
            (tr("5 minuti"), tr("per imperi grandi"))])
        if t is None:
            continue
        return {"scenario": sc.key, "humans": (sc.factions[f].key,),
                "difficulty": ("facile", "normale", "difficile")[d], "turn_time": times[t]}


def _faction_blurb(fd) -> str:
    doctrine = {"restrained": N("dottrina prudente"), "balanced": N("dottrina equilibrata"),
                "aggressive": N("dottrina aggressiva")}[fd.doctrine]
    parts = [tr(doctrine)]
    if fd.warheads:
        parts.append(tr("{n} testate", n=fd.warheads))
    if fd.industry != 1.0:
        parts.append(tr("economia di guerra ×{factor:g}", factor=fd.industry))
    if fd.capital_city:
        parts.append(tr("capitale {city}", city=fd.capital_city))
    return ", ".join(parts)
