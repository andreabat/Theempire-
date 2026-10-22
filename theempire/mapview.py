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
from theempire.i18n import N
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
COMMANDS = {"move", "order", "wake", "end_turn", "load", "unload", "disband", "produce", "release", "directive", "nuke", "chem", "asat", "card"}


def command(cmd) -> dict | None:
    """A command from a map page, if it is one it may give."""
    if not isinstance(cmd, dict) or cmd.get("op") not in COMMANDS:
        return None
    return {k: v for k, v in cmd.items() if k in ("op", "unit", "cell", "order", "target", "city", "key", "name", "all", "card")}


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


REEL_KEYS = ("op", "cell", "frm", "glyph", "owner", "attacker", "defender", "result", "target",
             "unit", "old", "new", "name", "actor", "victim")


def reel(game: Game, acts: list[dict], viewer: int, lang: str | None = None) -> list[dict]:
    """The war bulletin for the page to animate: what the others did, with
    the chronicle line of each scene in the reader's language."""
    from theempire import chronicle
    out = []
    for act in acts or []:
        if not isinstance(act, dict) or "op" not in act or "cell" not in act:
            continue
        item = {k: act[k] for k in REEL_KEYS if k in act}
        if act["op"] != "move":
            item["line"] = chronicle.scene_line(game, act, viewer, lang)
        out.append(item)
    return out


def production(g: Game, viewer: int, lang: str | None = None) -> dict:
    """What each city of the viewer builds, and what it could build instead
    (the same menu as the terminal's p)."""
    from theempire.game import DIRECTIVES
    from theempire.units import ASAT, CHEMICAL, PRODUCTION_NAMES, SATELLITE, WARHEAD, production_cost
    out = {}
    for c in g.cities_of(viewer):
        rate = g.production_rate(c)
        options = []
        for k in list(UNIT_TYPES) + [WARHEAD, CHEMICAL, SATELLITE, ASAT]:
            if not g.can_build(c, k):
                continue
            cost = production_cost(k)
            if k in UNIT_TYPES:
                t = UNIT_TYPES[k]
                stats = i18n.tr("att {attack} dif {defense} PV {hp} mosse {moves}", lang, attack=t.attack,
                                defense=t.defense, hp=t.hp, moves=t.move)
            elif k == SATELLITE:
                stats = i18n.tr("in orbita: vede una fascia del mondo", lang)
            else:
                stats = i18n.tr("scorta strategica", lang)
            options.append([k, i18n.word(PRODUCTION_NAMES[k], lang), cost,
                            None if rate <= 0 else int(-(-cost // rate)), stats])
        key = c.production
        out[c.id] = {"key": key, "name": i18n.word(PRODUCTION_NAMES.get(key, key), lang),
                     "progress": round(c.progress, 1), "cost": production_cost(key) if key in PRODUCTION_NAMES else 0,
                     "rate": round(rate, 1), "manual": c.manual, "options": options}
    directive = g.factions[viewer].directive
    return {"cities": out, "directive": directive,
            "directive_name": i18n.word(DIRECTIVES.get(directive, ""), lang).split(" (")[0] if directive else "",
            # the war economy's orders, as the terminal's P menu shows them
            "directives": [[k, i18n.word(v, lang)] for k, v in DIRECTIVES.items()],
            "manual": sum(1 for c in g.cities_of(viewer) if c.manual)}


def _longitude(lon: float) -> str:
    return f"{abs(lon):.0f}°{'E' if lon >= 0 else 'W'}"


def weapons(g: Game, viewer: int, lang: str | None = None) -> dict:
    """The viewer's weapons of mass destruction and its war in space."""
    from theempire.game import CHEM_RANGE
    fac = g.factions[viewer]
    w = g.world
    sats = []
    for k, x in enumerate(fac.satellites):
        band = g.satellite_band(x)
        west = w.lonlat(band.start % w.width)[0]
        east = w.lonlat((band.stop - 1) % w.width)[0]
        sats.append({"col": x, "from": band.start, "to": band.stop,
                     "text": i18n.tr("Satellite {n}: sorvola da {west} a {east}", lang, n=k + 1,
                                     west=_longitude(west), east=_longitude(east))})
    targets = [{"idx": o.idx, "label": i18n.tr("Lancia un'arma antisatellite contro {faction} ({n} satelliti)",
                                               lang, faction=o.name, n=len(o.satellites))}
               for o in g.factions if o.idx != viewer and o.alive]
    return {
        "warheads": fac.warheads, "nuclear": fac.nuclear, "chemicals": fac.chemicals,
        "chem_range": CHEM_RANGE, "modern": g.scenario.modern, "asats": fac.asats, "satellites": sats,
        "space_info": i18n.tr("Un satellite spia vede tutte le unità nemiche (tranne i sottomarini) in una "
                              "fascia larga 25° e mostra le loro mosse nel bollettino. Ogni turno sorvola "
                              "un'altra fascia. Si costruisce nelle città grandi o nelle capitali.", lang),
        "no_satellites": i18n.tr("Nessun satellite in orbita.", lang),
        "asats_text": i18n.tr("Armi antisatellite pronte: {n}", lang, n=fac.asats),
        "asat_targets": targets,
        "asat_hit": i18n.tr("Satellite nemico abbattuto!", lang),
    }


CARD_HINTS = {
    "own_city": N("♠ {card}: porta il cursore su una tua città e premi Invio."),
    "enemy_unit": N("♠ {card}: porta il cursore su un'unità nemica fuori dalle città e premi Invio."),
    "enemy_city": N("♠ {card}: porta il cursore su una città nemica e premi Invio."),
    "neutral_city": N("♠ {card}: porta il cursore su una città neutrale e premi Invio."),
}


def hand(g: Game, viewer: int, lang: str | None = None) -> dict:
    """The viewer's cards, as the terminal's K menu shows them, and the last
    report of its spies."""
    from theempire import cards
    out = []
    for key in g.factions[viewer].cards:
        c = cards.CARDS.get(key)
        if c is None:
            continue
        out.append({"key": key, "name": i18n.word(c.name, lang), "text": i18n.word(c.text, lang),
                    "target": c.target,
                    "odds": i18n.tr("riesce nel {pct}% dei casi", lang, pct=int(c.chance * 100))
                    if c.chance < 1 else "",
                    "hint": i18n.tr(CARD_HINTS[c.target], lang, card=c.name) if c.target in CARD_HINTS else ""})
    empty = [i18n.tr("Non hai carte.", lang), "",
             i18n.tr("Ne peschi una a fine turno con una probabilità che cresce con le", lang),
             i18n.tr("città conquistate nel turno: 20% per una piccola, 60% per una grande", lang),
             i18n.tr("o una capitale, al massimo 80%;", lang),
             i18n.tr("e una ogni {every} turni dai servizi segreti (massimo {limit} in mano).", lang,
                     every=cards.BRIEFING_EVERY, limit=cards.HAND_LIMIT)]
    intel = [e.shown(lang).lstrip("◈ ") for e in g.events
             if (e.audience is None or viewer in e.audience) and (e.msg[0] if e.msg else e.text).startswith("◈")][-6:]
    return {"cards": out, "limit": cards.HAND_LIMIT, "empty": empty, "intel": intel,
            "title": i18n.tr("Le tue carte ({n}/{limit})", lang, n=len(out), limit=cards.HAND_LIMIT),
            "intel_title": i18n.tr("◈ RAPPORTO DEI SERVIZI SEGRETI", lang),
            "not_your_turn": i18n.tr("Le carte si giocano nel tuo turno.", lang)}


def card_result(key: str, result: str, lang: str | None = None) -> str:
    """What the terminal says after playing a card."""
    from theempire import cards
    c = cards.CARDS.get(key)
    name = c.name if c else key
    if result == "ok":
        return i18n.tr("♠ {card}: fatto!", lang, card=name)
    if result == "failed":
        return i18n.tr("♠ {card}: il tentativo è fallito, la carta è persa.", lang, card=name)
    return i18n.tr("♠ {card}: {reason} La carta resta in mano.", lang, card=name,
                   reason=result_text(result, lang) or i18n.tr("non si può giocare così.", lang))


def view_game(g: Game, viewer: int, lang: str | None = None, with_territory: bool = True) -> dict:
    lang = lang or i18n.language()
    w = g.world
    vis = g.visible(viewer)
    units = []
    for u in g.units.values():
        mine = u.owner == viewer
        if u.carrier is not None and not mine:
            continue                     # aboard: the ship shows how many it carries
        # [id, kind, owner, cell, hp, cargo, moves, order, fuel, carrier]: our units
        # aboard are listed too (the map draws only their ship), to give them orders
        units.append([u.id, u.kind, u.owner, u.cell, u.hp, len(u.cargo),
                      u.moves if mine else None, u.order if mine else None, u.fuel if mine else None,
                      u.carrier])
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
        "production": production(g, viewer, lang),
        "weapons": weapons(g, viewer, lang),
        "hand": hand(g, viewer, lang),
    }
    if with_territory:
        out["territory"] = territory(g)
    return out
