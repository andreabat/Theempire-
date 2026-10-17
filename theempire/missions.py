"""Secret objectives, as in Risiko: every faction gets a mission at the
start that only it knows. Whoever completes it wins at once.

Kinds (stored in Faction.mission as a plain dict, so it saves as JSON):

* regions:   hold every city of two regions;
* eliminate: knock a given rival out of the war yourself. If somebody else
             does it first, the mission turns into "cities";
* cities:    hold a number of cities (fewer than a domination win);
* capitals:  hold a number of capitals that belonged to the rivals at the
             start (taken from them, not from the neutrals).
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from theempire import regions
from theempire.i18n import Msg, tr, word

if TYPE_CHECKING:
    from theempire.game import Game

CITY_MARGIN = 0.08    # "cities": this share of the world fewer than a domination win
CAPITAL_SHARE = 0.45  # "capitals": this share of the rivals' starting capitals,
CAPITAL_MAX = 12      # at most
REGION_GAIN = (45, 90)  # "regions": cities still to take in the two regions


def assign(game: "Game") -> None:
    rng = random.Random(game.rng.random())
    for f in game.factions:
        f.mission = _pick(game, f.idx, rng)


def _pick(game: "Game", f: int, rng: random.Random) -> dict:
    kinds = ["regions", "cities", "capitals"]
    if len(game.factions) > 2:
        kinds.append("eliminate")
    kind = rng.choice(kinds)
    if kind == "regions":
        pair = _region_pair(game, f, rng)
        if pair:
            return {"kind": "regions", "regions": pair}
        kind = "cities"
    if kind == "eliminate":
        rivals = [o.idx for o in game.factions if o.idx != f]
        return {"kind": "eliminate", "target": rng.choice(rivals)}
    if kind == "capitals":
        rivals = len(_rival_capitals(game, f))
        if rivals:
            return {"kind": "capitals", "count": max(1, min(CAPITAL_MAX, -int(-CAPITAL_SHARE * rivals // 1)))}
    return _cities(game, f)


def _rival_capitals(game: "Game", f: int) -> list:
    return [c for c in game.cities if c.capital and c.founder is not None and c.founder != f]


def _cities(game: "Game", f: int) -> dict:
    total = len(game.cities)
    start = game.factions[f].start_cities
    # the same target for everybody, as in the board game: the big empires
    # must not reach it just by taking the neutrals next door
    count = int((game.scenario.victory_share - CITY_MARGIN) * total)
    return {"kind": "cities", "count": max(start + int(0.1 * total), count)}


def _region_pair(game: "Game", f: int, rng: random.Random) -> list[str] | None:
    """Two regions the faction does not already hold, of fair size, the
    nearer ones (where it has cities) more likely."""
    sizes = {k: len(regions.cities_in(game, k)) for k in regions.REGIONS}
    mine = {k: sum(1 for c in regions.cities_in(game, k) if c.owner == f) for k in sizes}
    free = [k for k in sizes if mine[k] < sizes[k]]
    pairs = [(a, b) for i, a in enumerate(free) for b in free[i + 1:]
             if REGION_GAIN[0] <= sizes[a] + sizes[b] - mine[a] - mine[b] <= REGION_GAIN[1]]
    if not pairs:
        return None
    weights = [1 + 3 * (mine[a] > 0) + 3 * (mine[b] > 0) for a, b in pairs]
    return list(rng.choices(pairs, weights)[0])


# ------------------------------------------------------------------ reading
def message(game: "Game", f: int) -> Msg | None:
    """The objective in words, still to translate (for the log); None if
    there is none, or it is a rival's secret."""
    m = game.factions[f].mission
    kind = m.get("kind")
    if kind == "regions":
        a, b = (regions.REGIONS[k].name for k in m["regions"])
        return Msg("Conquista tutte le città di {a} e di {b}.", a=a, b=b)
    if kind == "eliminate":
        return Msg("Elimina {faction} dalla guerra (devi prendere tu l'ultima città).",
                   faction=game.factions[m["target"]].name)
    if kind == "cities":
        return Msg("Controlla {count} città.", count=m["count"])
    if kind == "capitals":
        return Msg("Conquista e tieni {count} capitali che all'inizio erano dei tuoi rivali.",
                   count=m["count"])
    return None


def text(game: "Game", f: int) -> str:
    """The objective in words, in the current language."""
    msg = message(game, f)
    return str(msg) if msg is not None else ""


def progress(game: "Game", f: int) -> str:
    """How far the faction is, in a few words (current language)."""
    m = game.factions[f].mission
    kind = m.get("kind")
    if kind == "regions":
        parts = []
        for k in m["regions"]:
            cities = regions.cities_in(game, k)
            parts.append(tr("{region} {held}/{total}", region=regions.REGIONS[k].short,
                            held=sum(c.owner == f for c in cities), total=len(cities)))
        return " · ".join(parts)
    if kind == "eliminate":
        name = word(game.factions[m["target"]].name).split()[-1]
        return tr("{faction}: {n} città da prendere", faction=name, n=len(game.cities_of(m["target"])))
    if kind == "cities":
        return tr("{held}/{count} città", held=len(game.cities_of(f)), count=m["count"])
    if kind == "capitals":
        held = sum(1 for c in _rival_capitals(game, f) if c.owner == f)
        return tr("{held}/{count} capitali nemiche", held=held, count=m["count"])
    return ""


def done(game: "Game", f: int) -> bool:
    m = game.factions[f].mission
    kind = m.get("kind")
    if kind == "regions":
        return all(regions.holder(game, k) == f for k in m["regions"])
    if kind == "eliminate":
        return bool(m.get("done"))
    if kind == "cities":
        return len(game.cities_of(f)) >= m["count"]
    if kind == "capitals":
        return sum(1 for c in _rival_capitals(game, f) if c.owner == f) >= m["count"]
    return False


def on_elimination(game: "Game", victim: int, by: int | None) -> None:
    """A faction is out: whoever had to eliminate it either made it or
    gets a new objective."""
    for f in game.factions:
        m = f.mission
        if m.get("kind") != "eliminate" or m.get("target") != victim or m.get("done"):
            continue
        if by == f.idx:
            m["done"] = True
        elif f.alive:
            f.mission = _cities(game, f.idx)
            game.log(Msg("Obiettivo segreto: {faction} è stato eliminato da altri. "
                         "Nuovo obiettivo: {mission}", faction=game.factions[victim].name,
                         mission=message(game, f.idx)), [f.idx], "alert", "alert")
