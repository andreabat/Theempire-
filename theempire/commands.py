"""Player commands: the only way a human changes the game.

The local interface and the network server both go through ``apply``, so
an online client can do exactly what a local player can and nothing more:
every command is validated against the faction that sent it.
"""

from __future__ import annotations

import random
from typing import Callable

from theempire.ai import AI
from theempire.game import DIRECTIVES, Game

ORDERS = (None, "sentry", "fortify", "auto", "goto")


def advance(game: Game, progress: Callable[[str], None] | None = None) -> None:
    """Play AI factions until a human is to move, then prepare that turn.
    Every AI action is recorded in ``game.replay`` so the interface can show
    the turn as an animated newsreel afterwards."""
    game.replay = []
    game.recording = True
    try:
        while not game.over and not game.faction.human:
            if progress:
                progress(game.faction.name)
            AI(game, game.current).play()
            game.end_turn()
    finally:
        game.recording = False
    if not game.over:
        prepare_human_turn(game)


def prepare_human_turn(game: Game) -> None:
    """Once per human turn: march units with goto orders and let the AI run
    delegated units and production."""
    key = [game.turn, game.current]
    if game.prepared == key:
        return
    game.prepared = key
    f = game.current
    for u in list(game.units_of(f)):
        if u.order == "goto" and u.id in game.units:
            game.follow_goto(u)
    game.apply_directive(f)   # cities taken since last turn follow the directive too
    AI(game, f).assist()
    for proposer in game.proposals_to(f):
        game.log(f"{game.factions[proposer].name} propone una tregua: premi O per rispondere.",
                 [f], "alert")


def apply(game: Game, f: int, cmd: dict, name: str = "",
          progress: Callable[[str], None] | None = None) -> str:
    """Validate and execute one command from faction ``f``."""
    op = cmd.get("op")
    if op == "chat":
        text = printable(str(cmd.get("text", "")))[:200].strip()
        if not text:
            return "empty"
        who = name or game.factions[f].name
        game.log(f"✉ {who}: {text}", None, "chat")
        return "ok"
    if game.over:
        return "over"
    if game.current != f:
        return "notyourturn"
    if op == "end_turn":
        game.end_turn()
        advance(game, progress)
        return "ok"
    if op == "move":
        u = _own_unit(game, f, cmd.get("unit"))
        cell = _cell(game, cmd.get("cell"))
        if u is None or cell is None:
            return "illegal"
        return game.move(u, cell)
    if op == "order":
        u = _own_unit(game, f, cmd.get("unit"))
        order = cmd.get("order")
        if u is None or order not in ORDERS:
            return "illegal"
        if order == "fortify" and u.type.domain != "land":
            return "illegal"
        if order == "goto":
            target = _cell(game, cmd.get("target"))
            if target is None or game.path(u, target) is None:
                return "unreachable"
            u.order, u.target = "goto", target
            game.follow_goto(u)
            return "ok"
        u.order, u.target = order, None
        return "ok"
    if op == "wake":
        cell = _cell(game, cmd.get("cell"))
        if cell is None:
            return "illegal"
        woke = 0
        for u in game.units_at(cell):
            for v in [u] + [game.units[c] for c in u.cargo if c in game.units]:
                if v.owner == f and v.order is not None:
                    v.order, v.target = None, None
                    woke += 1
        return str(woke)
    if op in ("load", "unload"):
        u = _own_unit(game, f, cmd.get("unit"))
        if u is None:
            return "illegal"
        return str(game.load(u) if op == "load" else game.unload(u))
    if op == "disband":
        u = _own_unit(game, f, cmd.get("unit"))
        if u is None:
            return "illegal"
        game.kill(u)
        return "ok"
    if op == "produce":
        cid = cmd.get("city")
        key = cmd.get("key")
        if not isinstance(cid, int) or not 0 <= cid < len(game.cities):
            return "illegal"
        city = game.cities[cid]
        if city.owner != f or not isinstance(key, str) or not game.can_build(city, key):
            return "illegal"
        city.production = key
        city.manual = True
        return "ok"
    if op == "release":
        cid = cmd.get("city")
        if not isinstance(cid, int) or not 0 <= cid < len(game.cities) or game.cities[cid].owner != f:
            return "illegal"
        game.cities[cid].manual = False
        game.apply_directive(f)
        return "ok"
    if op == "directive":
        name = cmd.get("name")
        if name not in DIRECTIVES:
            return "illegal"
        fac = game.factions[f]
        fac.directive = name
        fac.auto_production = name == "auto"
        if cmd.get("all"):  # the order overrides the hand-picked cities too
            for c in game.cities_of(f):
                c.manual = False
        changed = game.apply_directive(f)
        if name == "auto":
            ai = AI(game, f)
            ai._fields()
            ai.production()
        return str(changed)
    if op == "auto_production":  # older clients: the same as the "auto" directive
        on = bool(cmd.get("on"))
        game.factions[f].auto_production = on
        game.factions[f].directive = "auto" if on else ""
        return "ok"
    if op == "nuke":
        cell = _cell(game, cmd.get("cell"))
        if cell is None:
            return "illegal"
        city = game.city(cell)
        if city is not None and city.owner == f:
            return "own"
        return game.nuclear_strike(f, cell)
    if op == "chem":
        cell = _cell(game, cmd.get("cell"))
        if cell is None:
            return "illegal"
        return game.chemical_strike(f, cell)
    if op == "truce":
        target = cmd.get("target")
        if not isinstance(target, int) or not 0 <= target < len(game.factions) or target == f:
            return "illegal"
        return game.propose_truce(f, target)
    if op == "truce_answer":
        target = cmd.get("target")
        if not isinstance(target, int) or target not in game.proposals_to(f):
            return "illegal"
        return game.answer_truce(f, target, bool(cmd.get("accept")))
    return "unknown"


def printable(text: str) -> str:
    """Drop control characters, so nobody can send escape sequences to the
    other players' terminals."""
    return "".join(ch for ch in text if ch.isprintable())


def view_for(game: Game, f: int) -> dict:
    """The game state as faction ``f`` is allowed to see it.

    Enemy units outside its sight, the cargo of enemy ships, messages meant
    for others and the random generator (which would reveal combat rolls)
    are left out."""
    d = game.to_dict()
    seen = {u.id for u in game.units.values() if game.sees(f, u) and u.carrier is None}
    units = []
    for ud in d["units"]:
        if ud["owner"] == f:
            units.append(ud)
        elif ud["id"] in seen:
            units.append({**ud, "cargo": [], "order": None, "target": None})
    d["units"] = units
    d["events"] = [e for e in d["events"] if e["audience"] is None or f in e["audience"]]
    state = random.Random(0).getstate()
    d["rng"] = [state[0], list(state[1]), state[2]]
    return d


def _own_unit(game: Game, f: int, uid):
    if not isinstance(uid, int):
        return None
    u = game.units.get(uid)
    return u if u is not None and u.owner == f else None


def _cell(game: Game, cell):
    if not isinstance(cell, int) or not 0 <= cell < game.world.size:
        return None
    return cell


def describe(result: str) -> str:
    return {
        "illegal": "Movimento impossibile.", "nomoves": "Unità senza mosse.",
        "captured": "Città conquistata!", "lost": "Unità perduta.",
        "crashed": "L'aereo è precipitato.", "blocked": "Contatto con il nemico!",
        "notyourturn": "Non è il tuo turno.", "unreachable": "Destinazione irraggiungibile.",
        "intercepted": "Missile intercettato!", "nowarheads": "Nessuna testata disponibile.",
        "own": "Non puoi colpire una tua città.", "truce": "C'è una tregua in corso con quella fazione.",
        "over": "La partita è finita.", "cooldown": "Hai già proposto una tregua di recente.",
        "pending": "Proposta di tregua inviata.", "accepted": "Tregua accettata!",
        "refused": "Proposta di tregua respinta.",
    }.get(result, "")

