"""The chronicle of the war bulletin: one line for each thing the others
did, in the reader's language (the terminal and the graphical map share it)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from theempire.i18n import N, tr
from theempire.units import UNIT_TYPES

if TYPE_CHECKING:
    from theempire.game import Game


def place(g: "Game", cell: int, bare: bool = False, lang: str | None = None) -> str:
    """'a Vilnius', 'presso Vilnius' or coordinates, for the chronicle
    (``bare``: only the name of the place)."""
    city = g.city(cell)
    if city is not None:
        return city.name if bare else tr("a {place}", lang, place=city.name)
    near = min(g.cities, key=lambda c: g.world.dist(c.cell, cell))
    if g.world.dist(near.cell, cell) <= 4:
        return near.name if bare else tr("presso {place}", lang, place=near.name)
    lon, lat = g.world.lonlat(cell)
    where = f"{abs(lat):.0f}°{'N' if lat >= 0 else 'S'} {abs(lon):.0f}°{'E' if lon >= 0 else 'W'}"
    return where if bare else tr("a {place}", lang, place=where)


def scene_line(g: "Game", act: dict, me: int, lang: str | None = None) -> str:
    """One line of chronicle for a bulletin scene (moves have none)."""
    op = act["op"]
    if op == "attack":
        kind = act.get("glyph", "")
        who = UNIT_TYPES[kind].name if kind in UNIT_TYPES else N("Unità")
        tgt = act.get("target") or ""
        result = act.get("result")
        city = g.city(act["cell"])
        if tgt in UNIT_TYPES:
            where = tr("su {unit} {place}", lang, unit=UNIT_TYPES[tgt].name,
                       place=place(g, act["cell"], lang=lang))
        else:
            where = tr("sulla città di {city}", lang, city=city.name) if city else \
                place(g, act["cell"], lang=lang)
        if act.get("defender") == me:
            outcome = {"lost": N("RESPINTO"), "captured": N("LA CITTÀ CADE")}.get(
                result, N("PERDIAMO l'unità") if tgt in UNIT_TYPES else N("difese a terra"))
            return tr("⚔ CONTRO DI NOI · {unit} ({attacker}) {where} → {outcome}", lang, unit=who,
                      attacker=g.faction_name(act.get("attacker")), where=where, outcome=outcome)
        outcome = {"lost": N("fallisce"), "captured": N("la città cade")}.get(result, N("bersaglio distrutto"))
        return tr("⚔ {unit} ({attacker}) {where} ({defender}) → {outcome}", lang, unit=who,
                  attacker=g.faction_name(act.get("attacker")), where=where,
                  defender=g.faction_name(act.get("defender")), outcome=outcome)
    if op == "capture":
        params = dict(city=act.get("name", "?"), new=g.faction_name(act.get("new")),
                      old=g.faction_name(act.get("old")))
        if act.get("old") == me:
            return tr("⚑ {city} conquistata da {new} (prima: {old}) — PERSA", lang, **params)
        return tr("⚑ {city} conquistata da {new} (prima: {old})", lang, **params)
    if op == "fall":
        return tr("✖ {faction} ha perso l'ultima città: è fuori dalla guerra", lang,
                  faction=g.faction_name(act.get("old")))
    if op == "nuke":
        return tr("☢ {faction} colpisce {place} con un'arma nucleare", lang,
                  faction=g.faction_name(act.get("actor")), place=act.get("name", "?"))
    if op == "chem":
        return tr("☣ {faction} usa armi chimiche su {place}", lang,
                  faction=g.faction_name(act.get("actor")), place=act.get("name", "?"))
    if op == "card":
        params = dict(faction=g.faction_name(act.get("actor")), card=act.get("name", "?"),
                      text=act.get("text", ""))
        if act.get("victim") == me:
            return tr("♠ {faction} gioca «{card}»: {text} — CONTRO DI NOI", lang, **params)
        return tr("♠ {faction} gioca «{card}»: {text}", lang, **params)
    return ""
