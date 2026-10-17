"""Player commands: the only way a human changes the game.

The local interface and the network server both go through ``apply``, so
an online client can do exactly what a local player can and nothing more:
every command is validated against the faction that sent it.
"""

from __future__ import annotations

import random
from typing import Callable

from theempire import cards
from theempire.ai import AI
from theempire.game import DIRECTIVES, Game
from theempire.i18n import N, Msg, tr

ORDERS = (None, "sentry", "fortify", "auto", "goto")


def advance(game: Game, progress: Callable[[str], None] | None = None) -> None:
    """Play AI factions until a human is to move, then prepare that turn."""
    while not game.over and not game.faction.human:
        if progress:
            progress(game.faction.name)
        AI(game, game.current).play()
        game.end_turn()
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
        game.log(Msg("{faction} propone una tregua: premi O per rispondere.",
                     faction=game.factions[proposer].name), [f], "alert")


def apply(game: Game, f: int, cmd: dict, name: str = "",
          progress: Callable[[str], None] | None = None) -> str:
    """Validate and execute one command from faction ``f``."""
    op = cmd.get("op")
    if op == "chat":
        text = printable(str(cmd.get("text", "")))[:200].strip()
        if not text:
            return "empty"
        who = name or game.factions[f].name
        game.log(Msg("✉ {who}: {text}", who=who, text=text), None, "chat")
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
    if op == "asat":
        target = cmd.get("target")
        if not isinstance(target, int) or not 0 <= target < len(game.factions):
            return "illegal"
        return game.asat_strike(f, target)
    if op == "chem":
        cell = _cell(game, cmd.get("cell"))
        if cell is None:
            return "illegal"
        return game.chemical_strike(f, cell)
    if op == "card":
        target = cmd.get("target")
        cell = cmd.get("cell")
        return cards.play(game, f, str(cmd.get("card", "")),
                          cell if isinstance(cell, int) else None,
                          target if isinstance(target, int) else None)
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


MAX_REEL_MOVES = 120


def newsreel(game: Game, f: int) -> list[dict]:
    """The war bulletin for faction ``f``: what the others did since its
    last turn, as far as it may know. Strikes, captures and falls are news
    for everybody; moves and battles only where its forces see, or when
    they hit it. A very long reel keeps every battle but thins the marches."""
    vis = game.visible(f)
    kept = []
    for act in game.take_reel(f):
        op = act["op"]
        if op in ("nuke", "chem", "capture", "fall"):
            kept.append(act)
        elif op == "card":
            if act.get("public") or act.get("victim") == f:
                kept.append(act)
        elif op == "attack":
            if act.get("defender") == f or act["cell"] in vis:
                kept.append(act)
        elif act["cell"] in vis:
            kept.append(act)
    moves = [a for a in kept if a["op"] == "move"]
    if len(moves) > MAX_REEL_MOVES:
        step = len(moves) / MAX_REEL_MOVES
        keep = {moves[int(k * step)]["seq"] for k in range(MAX_REEL_MOVES)}
        kept = [a for a in kept if a["op"] != "move" or a["seq"] in keep]
    return kept


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
    # cards are secret: rivals only show how many they hold
    for fd in d["factions"]:
        if fd["idx"] != f:
            fd["cards"] = ["?"] * len(fd["cards"])
            fd["effects"] = {}
            if not game.over:
                fd["mission"] = {"kind": "secret"} if fd.get("mission") else {}
                # how many satellites they have is known, not where they fly
                fd["satellites"] = [-1] * len(fd.get("satellites", []))
                fd["asats"] = 0
    d["deck"] = ["?"] * len(d["deck"])
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


# The message for each result code of a command.
RESULTS = {
    "illegal": N("Movimento impossibile."), "nomoves": N("Unità senza mosse."),
    "captured": N("Città conquistata!"), "lost": N("Unità perduta."),
    "crashed": N("L'aereo è precipitato."), "blocked": N("Contatto con il nemico!"),
    "notyourturn": N("Non è il tuo turno."), "unreachable": N("Destinazione irraggiungibile."),
    "intercepted": N("Missile intercettato!"), "nowarheads": N("Nessuna testata disponibile."),
    "own": N("Non puoi colpire una tua città."), "truce": N("C'è una tregua in corso con quella fazione."),
    "over": N("La partita è finita."), "failed": N("Carta giocata, ma il tentativo è fallito."),
    "notarget": N("Bersaglio non valido per questa carta."),
    "card_own_city": N("Scegli una tua città."),
    "card_neutral_city": N("Scegli una città neutrale."),
    "card_country_taken": N("Quel paese ha già città in mano a qualcuno: niente colpo di stato."),
    "card_country_big": N("Il colpo di stato riesce solo nei paesi con al massimo 4 città."),
    "card_no_friends": N("Serve una tua unità entro 3 caselle da una città di quel paese."),
    "card_not_city": N("Scegli una città: porta il cursore proprio sulla città."),
    "card_not_enemy_city": N("Non è una città nemica (le città neutrali e quelle in tregua non valgono)."),
    "card_seat": N("È la capitale principale della fazione: lì la rivolta non attecchisce."),
    "card_too_big": N("Città troppo grande (dimensione 3): la rivolta riesce solo nelle città di dimensione 1-2."),
    "card_unit_in_city": N("Le unità dentro le città non si possono colpire con questa carta."),
    "card_no_enemy_unit": N("Lì non c'è un'unità nemica che le tue forze vedono."),
    "card_not_adjacent": N("Il commando agisce solo accanto a una tua unità."),
    "cooldown": N("Hai già proposto una tregua di recente."),
    "pending": N("Proposta di tregua inviata."), "accepted": N("Tregua accettata!"),
    "refused": N("Proposta di tregua respinta."),
    "noasat": N("Nessuna arma antisatellite: costruiscine una in una città grande."),
    "nosat": N("Quella fazione non ha satelliti in orbita."),
    "missed": N("L'arma antisatellite ha mancato il bersaglio."),
}


def describe(result: str) -> str:
    """The message for a result code, in the current language."""
    text = RESULTS.get(result, "")
    return tr(text) if text else ""

