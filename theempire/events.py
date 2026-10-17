"""World events, as the event cards of a board game: every few rounds
something happens that touches everybody and upsets the plans.

An event either acts at once (a revolt, a hurricane, a summit) or sets a
world effect for a few turns (Game.world_effects: name -> last turn), read
by the rules where it matters (movement, production).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from theempire.game import Game

EVERY = (5, 8)          # rounds between two events (random in this range)
LASTS = 3               # turns a world effect lasts
SUMMIT_TRUCE = 6        # turns of the truce imposed by the UN


@dataclass(frozen=True)
class WorldEvent:
    key: str
    name: str
    text: str
    act: Callable[["Game"], str | None]   # returns the detail line, None = cannot happen now


def _effect(key: str) -> Callable[["Game"], str]:
    def act(game: "Game") -> str:
        game.world_effects[key] = game.turn + LASTS - 1
        return f"Per {LASTS} turni."
    return act


def _summit(game: "Game") -> str | None:
    alive = [f for f in game.factions if f.alive]
    pairs = [(a, b) for i, a in enumerate(alive) for b in alive[i + 1:] if game.hostile(a.idx, b.idx)]
    if not pairs:
        return None
    a, b = max(pairs, key=lambda p: game.score(p[0]) + game.score(p[1]))
    game.truces[game._pair(a.idx, b.idx)] = game.turn + SUMMIT_TRUCE
    game.proposals = [p for p in game.proposals if set(p) != {a.idx, b.idx}]
    return f"Tregua imposta tra {a.name} e {b.name} per {SUMMIT_TRUCE} turni."


def _uprising(game: "Game") -> str | None:
    alive = [f for f in game.factions if f.alive and len(game.cities_of(f.idx)) > 3]
    if not alive:
        return None
    biggest = max(alive, key=lambda f: len(game.cities_of(f.idx)))
    cities = [c for c in game.cities_of(biggest.idx) if not c.capital and not game.units_at(c.cell)]
    if not cities:
        return None
    c = game.rng.choice(cities)
    c.owner = None
    c.production = "I"
    c.progress = 0.0
    c.manual = False
    c.militia = c.militia_max()
    game.record("capture", c.cell, None, old=biggest.idx, new=None, name=c.name)
    game._dirty()
    return f"{c.name} insorge contro {biggest.name} e torna neutrale."


def _hurricane(game: "Game") -> str | None:
    ships = [u for u in game.units.values() if u.type.domain == "sea" and u.carrier is None
             and game.city(u.cell) is None]
    if not ships:
        return None
    eye = game.rng.choice(ships).cell
    hit = 0
    for u in list(game.units.values()):
        if u.carrier is None and u.type.domain in ("sea", "air") and game.city(u.cell) is None \
                and game.world.dist(u.cell, eye) <= 6 and u.hp > 1:
            u.hp -= 1
            hit += 1
    lon, lat = game.world.lonlat(eye)
    where = f"{abs(lat):.0f}°{'N' if lat >= 0 else 'S'} {abs(lon):.0f}°{'E' if lon >= 0 else 'W'}"
    return f"Un uragano a {where} danneggia {hit} unità in mare e in volo."


def _arms_race(game: "Game") -> str:
    got = [f.name for f in game.factions if f.alive and f.nuclear]
    for f in game.factions:
        if f.alive and f.nuclear:
            f.warheads += 1
    game.doomsday -= 1
    game.quiet_turns = 0
    game._check_clock()
    return (f"Una testata in più a: {', '.join(got) or 'nessuno'}. "
            f"L'Orologio dell'Apocalisse avanza a {game.doomsday} minuti.")


def _thaw(game: "Game") -> str | None:
    if game.doomsday >= game.scenario.doomsday:
        return None
    game.doomsday += 1
    return f"L'Orologio dell'Apocalisse torna a {game.doomsday} minuti dalla mezzanotte."


def _volunteers(game: "Game") -> str:
    names = []
    for f in game.factions:
        if not f.alive:
            continue
        cities = game.cities_of(f.idx)
        home = next((c for c in cities if c.capital), cities[0] if cities else None)
        if home is not None:
            game.create_unit("I", f.idx, home.cell)
            names.append(home.name)
    return f"Una fanteria di volontari in più a {', '.join(names)}."


EVENTS: dict[str, WorldEvent] = {e.key: e for e in (
    WorldEvent("oil", "Crisi petrolifera",
               "Il greggio è razionato: aerei e navi hanno metà delle mosse.", _effect("oil")),
    WorldEvent("famine", "Carestia",
               "Raccolti perduti: le città grandi (dimensione 3) producono il 30% in meno.",
               _effect("famine")),
    WorldEvent("boom", "Boom economico",
               "Le fabbriche lavorano a pieno ritmo: +25% di produzione per tutti.", _effect("boom")),
    WorldEvent("winter", "Inverno rigido",
               "Neve e gelo oltre il 45° parallelo nord: le unità di terra lassù muovono di 1 in meno.",
               _effect("winter")),
    WorldEvent("summit", "Vertice dell'ONU",
               "Le Nazioni Unite impongono il cessate il fuoco tra le due potenze più forti in guerra.",
               _summit),
    WorldEvent("uprising", "Insurrezione",
               "Una città della fazione più estesa si ribella.", _uprising),
    WorldEvent("hurricane", "Uragano", "Una tempesta colpisce un tratto di mare.", _hurricane),
    WorldEvent("arms_race", "Corsa agli armamenti",
               "Ogni potenza nucleare costruisce una testata; il mondo si avvicina alla mezzanotte.",
               _arms_race),
    WorldEvent("thaw", "Disgelo diplomatico", "La tensione internazionale cala.", _thaw),
    WorldEvent("volunteers", "Volontari", "Ogni capitale riceve una fanteria di volontari.",
               _volunteers),
)}


def active(game: "Game", key: str) -> bool:
    return game.world_effects.get(key, 0) >= game.turn


def schedule(game: "Game") -> None:
    game.next_event = game.turn + game.rng.randint(*EVERY)


def new_round(game: "Game") -> None:
    """Called at the start of every round: time for an event?"""
    for key in [k for k, end in game.world_effects.items() if end < game.turn]:
        del game.world_effects[key]
    if not game.options["world_events"] or game.over:
        return
    if not game.next_event:
        schedule(game)
    if game.turn < game.next_event:
        return
    schedule(game)
    keys = list(EVENTS)
    game.rng.shuffle(keys)
    for key in keys:
        if key not in game.world_effects and fire(game, key):
            return


def fire(game: "Game", key: str) -> bool:
    """Make event ``key`` happen now and announce it. False if it cannot."""
    event = EVENTS[key]
    detail = event.act(game)
    if detail is None:
        return False
    game.log(f"EVENTO MONDIALE · {event.name}: {event.text} {detail}", None, "world", "alert")
    return True


def describe_active(game: "Game") -> list[str]:
    """The world effects in force, for the panel."""
    return [f"{EVENTS[k].name} ({end - game.turn + 1}t)" for k, end in sorted(game.world_effects.items())
            if end >= game.turn]
