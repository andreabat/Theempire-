"""The graphical web map: what its page needs, as compact JSON.

The page (assets/web/map.html) draws the world on a canvas, like the SVG
fallback of a dashboard map: the fine land mask as an image, the territory
of each city, the fog of war, the grid (squares or hexagons) and the units
as wargame counters. It never sees more than the faction it watches: the
state comes from the server already filtered (commands.view_for).

* ``world(hexgrid)``: the fixed part, sent once: size, the land of every
  cell, the city sites;
* ``land_png()``: the fine land mask (world.load_hd) as a 1-bit PNG;
* ``view(state, viewer, lang)``: one moment of the game for the viewer.
"""

from __future__ import annotations

import base64
import struct
import zlib
from collections import deque
from datetime import date, timedelta
from functools import lru_cache

from theempire import i18n
from theempire.game import Game
from theempire.units import SYMBOLS, UNIT_TYPES
from theempire.world import load_hd, load_world

START_DATES = {"ww3": date(2027, 3, 1), "coldwar": date(1985, 8, 4)}   # as in the terminal


def _bits(flags) -> str:
    """A list of booleans, packed 8 to a byte (most significant first), in base64."""
    out = bytearray((len(flags) + 7) // 8)
    for i, on in enumerate(flags):
        if on:
            out[i >> 3] |= 0x80 >> (i & 7)
    return base64.b64encode(bytes(out)).decode("ascii")


@lru_cache(maxsize=2)
def world(hexgrid: bool = False) -> dict:
    w = load_world(hexgrid)
    hd = load_hd()
    return {
        "width": w.width, "height": w.height,
        "lon0": w.lon0, "lat0": w.lat0, "dlon": w.dlon, "dlat": w.dlat,
        "hex": w.hexgrid,
        "land": _bits(w.land),
        # the fine mask: how many of its pixels make one cell, each way
        "hd": [hd.width // w.width, hd.height // w.height] if hd else None,
    }


@lru_cache(maxsize=1)
def land_png() -> bytes | None:
    """The fine land mask as a PNG: white land, transparent sea."""
    hd = load_hd()
    if hd is None:
        return None

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\0" + hd.bits[y * hd.stride:(y + 1) * hd.stride] for y in range(hd.height))
    # 1-bit palette: 0 = transparent sea, 1 = white land
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", hd.width, hd.height, 1, 3, 0, 0, 0))
            + chunk(b"PLTE", b"\0\0\0\xff\xff\xff")
            + chunk(b"tRNS", b"\0\xff")
            + chunk(b"IDAT", zlib.compress(rows, 9))
            + chunk(b"IEND", b""))


_territory_cache: dict[tuple, list[int]] = {}


def territory(game: Game) -> list[int]:
    """Which city each land cell belongs to (the nearest over land, as in
    the terminal map); -1 for the sea."""
    w = game.world
    key = (w.hexgrid, tuple(c.cell for c in game.cities))
    if key not in _territory_cache:
        src = [-1] * w.size
        queue = deque()
        for c in game.cities:
            src[c.cell] = c.id
            queue.append(c.cell)
        while queue:
            cur = queue.popleft()
            for n in w.neighbors[cur]:
                if w.land[n] and src[n] < 0:
                    src[n] = src[cur]
                    queue.append(n)
        if len(_territory_cache) > 8:
            _territory_cache.clear()
        _territory_cache[key] = src
    return _territory_cache[key]


def territory_key(game: Game) -> str:
    return f"{int(game.world.hexgrid)}:{zlib.crc32(repr([c.cell for c in game.cities]).encode())}"


def _date(game: Game, lang: str) -> str:
    start = START_DATES.get(game.scenario.key)
    if start is None:
        return i18n.tr("Anno {year}, sett. {week}", lang, year=1 + (game.turn - 1) // 52,
                       week=1 + (game.turn - 1) % 52)
    day = start + timedelta(weeks=game.turn - 1)
    months = i18n.tr("gen feb mar apr mag giu lug ago set ott nov dic", lang).split()
    return f"{day.day} {months[day.month - 1]} {day.year}"


def view(state: dict, viewer: int, lang: str | None = None, with_territory: bool = True) -> dict:
    """One moment of the game, as the viewer's faction sees it."""
    return view_game(Game.from_dict(state), viewer, lang, with_territory)


# what a map page may ask the server to do (the rest stays in the TUI for now)
COMMANDS = {"move", "order", "wake", "end_turn", "load", "unload", "disband"}


def command(cmd) -> dict | None:
    """A command from a map page, if it is one it may give."""
    if not isinstance(cmd, dict) or cmd.get("op") not in COMMANDS:
        return None
    return {k: v for k, v in cmd.items() if k in ("op", "unit", "cell", "order", "target")}


def result_text(result: str, lang: str | None = None) -> str:
    from theempire.commands import RESULTS
    text = RESULTS.get(result, "")
    return i18n.tr(text, lang) if text else ""


def path(game: Game, viewer: int, unit, cell) -> list[int] | None:
    """The route a unit of the viewer would take (None: no way there)."""
    u = game.units.get(unit) if isinstance(unit, int) else None
    if u is None or u.owner != viewer or not isinstance(cell, int) or not 0 <= cell < game.world.size:
        return None
    return game.path(u, cell)


def view_game(g: Game, viewer: int, lang: str | None = None, with_territory: bool = True) -> dict:
    lang = lang or i18n.language()
    w = g.world
    vis = g.visible(viewer)
    units = []
    for u in g.units.values():
        if u.carrier is not None:
            continue                     # aboard: the ship shows how many it carries
        mine = u.owner == viewer
        units.append([u.id, u.kind, u.owner, u.cell, u.hp, len(u.cargo),
                      u.moves if mine else None, u.order if mine else None, u.fuel if mine else None])
    out = {
        "viewer": viewer,
        "hex": w.hexgrid,
        "scenario": i18n.word(g.scenario.name, lang),
        "turn": g.turn, "current": g.current, "date": _date(g, lang),
        "doomsday": g.doomsday, "realtime": g.realtime,
        "over": g.over,
        "factions": [{"idx": f.idx, "name": i18n.word(f.name, lang), "color": f.color,
                      "alive": f.alive, "human": f.human, "cities": len(g.cities_of(f.idx)),
                      "warheads": f.warheads if f.idx == viewer else None}
                     for f in g.factions],
        "neutral": len(g.cities_of(None)),
        "cities": [[c.id, c.name, c.cell, c.size, int(c.capital),
                    -1 if c.owner is None else c.owner] for c in g.cities],
        "units": units,
        "visible": _bits([i in vis for i in range(w.size)]),
        "theatre": _bits(g.theatre) if g.theatre is not None else None,
        "fallout": [c for c, _ in g.fallout.items()],
        "events": [{"turn": e.turn, "text": e.shown(lang), "level": e.level}
                   for e in g.events if e.audience is None or viewer in e.audience][-14:],
        "my_turn": bool(g.realtime or g.current == viewer) and not g.over,
        "unit_types": {k: {"name": i18n.word(t.name, lang), "move": t.move, "hp": t.hp,
                           "domain": t.domain, "fuel": t.fuel} for k, t in UNIT_TYPES.items()},
        "symbols": SYMBOLS,
        "territory_key": territory_key(g),
    }
    if with_territory:
        out["territory"] = territory(g)
    return out
