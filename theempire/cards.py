"""Cards, in the spirit of Futurisiko: a hand of secret cards that bend the
war a little. They are earned by conquering (one card at the end of a turn
in which you took at least one city) and by intelligence briefings (one
card every few turns for everybody), and played instead of moving units.

Every card is resolved here, on the authoritative game, so online clients
can only ask to play a card they really hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from theempire.units import UNIT_TYPES

if TYPE_CHECKING:
    from theempire.game import Game

HAND_LIMIT = 5
BRIEFING_EVERY = 6      # turns between free intelligence cards


@dataclass(frozen=True)
class Card:
    key: str
    name: str
    text: str
    target: str          # none | own_city | enemy_unit | enemy_city | neutral_city | faction
    copies: int
    chance: float = 1.0  # probability that it works (shown to the player)


CARDS: dict[str, Card] = {c.key: c for c in (
    Card("plan", "Piano quinquennale",
         "+50% di produzione in tutte le tue città per 3 turni.", "none", 3),
    Card("mobilize", "Mobilitazione generale",
         "Ogni tua città guadagna subito un turno di produzione.", "none", 2),
    Card("reinforce", "Rinforzi",
         "Compaiono 2 fanterie e 1 corazzato in una tua città (oltre il limite logistico).",
         "own_city", 3),
    Card("defect", "Diserzione",
         "Un'unità nemica che vedi, fuori dalle città, passa dalla tua parte.",
         "enemy_unit", 3, 0.65),
    Card("commando", "Commando",
         "Un'unità nemica accanto alle tue forze, fuori dalle città, viene eliminata.",
         "enemy_unit", 2, 0.7),
    Card("revolt", "Rivolta",
         "Una città nemica (non capitale, dimensione 1-2) insorge: diventa neutrale, "
         "o tua se hai truppe di terra accanto.", "enemy_city", 2, 0.6),
    Card("coup", "Colpo di stato",
         "Un paese neutrale con al massimo 4 città, dove hai un'unità entro 3 caselle, "
         "passa con te.", "neutral_city", 1, 0.5),
    Card("spy", "Spionaggio",
         "Vedi tutte le unità di una fazione fino al tuo prossimo turno, con un rapporto "
         "su città, eserciti, testate e produzione.", "faction", 3),
    Card("sabotage", "Sabotaggio",
         "In una città nemica la produzione riparte da zero e scoppiano 3 turni di disordini.",
         "enemy_city", 2, 0.75),
    Card("shield", "Scudo antimissile",
         "+50% di probabilità di intercettare i missili per 6 turni.", "none", 1),
    Card("detente", "Distensione",
         "Un vertice di pace: l'Orologio dell'Apocalisse torna indietro di 3 minuti.", "none", 2),
)}


def new_deck(rng) -> list[str]:
    deck = [c.key for c in CARDS.values() for _ in range(c.copies)]
    rng.shuffle(deck)
    return deck


def draw(game: "Game", f: int, why: str) -> str | None:
    """Draw one card for ``f`` (nothing if the hand is full)."""
    fac = game.factions[f]
    if len(fac.cards) >= HAND_LIMIT:
        return None
    if not game.deck:
        game.deck, game.discard = game.discard, []
        game.rng.shuffle(game.deck)
    if not game.deck:
        return None
    card = game.deck.pop()
    fac.cards.append(card)
    game.log(f"♠ {why}: peschi la carta «{CARDS[card].name}» (K per giocarla).", [f], "alert", "card", f)
    return card


def end_of_turn(game: "Game", f: int) -> None:
    """Risiko's rule: whoever conquered this turn draws a card."""
    fac = game.factions[f]
    if fac.conquests > 0 and fac.alive:
        draw(game, f, "Conquista")
    fac.conquests = 0


def active(game: "Game", f: int, effect: str) -> bool:
    end = game.factions[f].effects.get(effect)
    return isinstance(end, int) and end >= game.turn


def spied(game: "Game", f: int) -> int | None:
    """The faction ``f`` is currently spying on, if any."""
    spy = game.factions[f].effects.get("spy")
    if isinstance(spy, list) and len(spy) == 2 and spy[1] >= game.turn:
        return spy[0]
    return None


# ------------------------------------------------------------------- play
def play(game: "Game", f: int, key: str, cell: int | None = None,
         target: int | None = None) -> str:
    """Play card ``key`` from ``f``'s hand. Returns a result code:
    ok / failed (the attempt was made, the card is spent) / illegal."""
    fac = game.factions[f]
    if key not in CARDS or key not in fac.cards or game.over:
        return "illegal"
    card = CARDS[key]
    check = _check(game, f, card, cell, target)
    if check is not None:
        return check
    fac.cards.remove(key)
    game.discard.append(key)
    if game.rng.random() >= card.chance:
        _failed(game, f, card, cell, target)
        return "failed"
    return EFFECTS[key](game, f, cell, target)


def _check(game: "Game", f: int, card: Card, cell: int | None, target: int | None) -> str | None:
    """None if the target is valid, else the reason code."""
    if card.target == "none":
        return None
    if card.target == "faction":
        ok = isinstance(target, int) and 0 <= target < len(game.factions) and target != f \
            and game.factions[target].alive
        return None if ok else "illegal"
    if not isinstance(cell, int) or not 0 <= cell < game.world.size:
        return "illegal"
    city = game.city(cell)
    if card.target == "own_city":
        return None if city is not None and city.owner == f else "notarget"
    if card.target == "neutral_city":
        if city is None or city.owner is not None:
            return "notarget"
        same = [c for c in game.cities if c.iso == city.iso]
        if any(c.owner is not None for c in same) or len(same) > 4:
            return "notarget"
        # a coup needs friends on the spot: one of our units near the country
        if not any(u.owner == f and u.carrier is None and game.world.dist(u.cell, c.cell) <= 3
                   for c in same for u in game.units.values()):
            return "notarget"
        return None
    if card.target == "enemy_city":
        if city is None or city.owner is None or not game.hostile(f, city.owner):
            return "notarget"
        if card.key == "revolt" and (city.capital or city.size > 2):
            return "notarget"
        return None
    if card.target == "enemy_unit":
        if city is not None:
            return "notarget"
        enemies = [u for u in game.units_at(cell) if game.hostile(f, u.owner) and game.sees(f, u)]
        if not enemies:
            return "notarget"
        if card.key == "commando" and not any(
                o.owner == f for c in game.world.ring(cell, 1) for o in game.units_at(c)):
            return "notarget"
        return None
    return "illegal"


def _victim(game: "Game", cell: int | None, target: int | None) -> int | None:
    if target is not None:
        return target
    if cell is None:
        return None
    city = game.city(cell)
    if city is not None:
        return city.owner
    owners = [u.owner for u in game.units_at(cell)]
    return owners[0] if owners else None


def _announce(game: "Game", f: int, card: Card, text: str, cell: int | None,
              target: int | None, public: bool = False, success: bool = True) -> None:
    victim = _victim(game, cell, target)
    audience = None if public else [f] + ([victim] if victim is not None and victim != f else [])
    game.log(f"♠ {game.factions[f].name} gioca «{card.name}»: {text}", audience, "alert", "card", f)
    if cell is not None and (victim is not None or public):
        game.record("card", cell, f, card=card.key, name=card.name, victim=victim,
                    public=public, success=success, text=text)


def _failed(game: "Game", f: int, card: Card, cell, target) -> None:
    _announce(game, f, card, "il tentativo fallisce.", cell, target, success=False)


def _plan(game, f, cell, target) -> str:
    game.factions[f].effects["plan"] = game.turn + 2
    _announce(game, f, CARDS["plan"], "produzione +50% per 3 turni.", None, None)
    return "ok"


def _mobilize(game, f, cell, target) -> str:
    for c in game.cities_of(f):
        c.progress += game.production_rate(c)
    _announce(game, f, CARDS["mobilize"], "le fabbriche lavorano giorno e notte.", None, None)
    return "ok"


def _reinforce(game, f, cell, target) -> str:
    for kind in "IIA":
        game.create_unit(kind, f, cell)
    _announce(game, f, CARDS["reinforce"], f"nuove truppe a {game.city(cell).name}.", None, None)
    return "ok"


def _best_enemy(game, f, cell):
    enemies = [u for u in game.units_at(cell) if game.hostile(f, u.owner) and game.sees(f, u)]
    return max(enemies, key=lambda u: (u.type.cost, u.hp))


def _defect(game, f, cell, target) -> str:
    u = _best_enemy(game, f, cell)
    old = u.owner
    for v in [u] + [game.units[c] for c in u.cargo if c in game.units]:
        v.owner = f
        v.order, v.target = None, None
        v.moves = 0
    game._dirty()
    _announce(game, f, CARDS["defect"],
              f"{u.type.name} di {game.faction_name(old)} diserta e passa con "
              f"{game.factions[f].name}!", cell, old)
    return "ok"


def _commando(game, f, cell, target) -> str:
    u = _best_enemy(game, f, cell)
    old, name = u.owner, u.type.name
    game.kill(u)
    _announce(game, f, CARDS["commando"], f"{name} di {game.faction_name(old)} eliminato.", cell, old)
    return "ok"


def _revolt(game, f, cell, target) -> str:
    city = game.city(cell)
    old = city.owner
    ours = any(o.owner == f and o.type.domain == "land"
               for n in game.world.neighbors[cell] for o in game.units_at(n))
    for u in list(game.units_at(cell)):
        if ours and u.type.domain == "land":
            u.owner, u.order, u.moves = f, None, 0       # the garrison joins the rebels
        else:
            game.kill(u)
    city.owner = f if ours else None
    city.progress = 0.0
    city.unrest = 3
    city.manual = False
    city.militia = city.militia_max()
    if ours:
        city.production = game._default_production(city)
        game.factions[f].conquests += 1
    who = f"si unisce a {game.factions[f].name}" if ours else "si proclama neutrale"
    _announce(game, f, CARDS["revolt"], f"{city.name} insorge e {who}!", cell, old, public=True)
    game._dirty()
    if old is not None and not game.cities_of(old):
        game.eliminate(old)
    return "ok"


def _coup(game, f, cell, target) -> str:
    city = game.city(cell)
    country = [c for c in game.cities if c.iso == city.iso]
    for c in country:
        c.owner = f
        c.unrest = 3
        c.progress = 0.0
        c.militia = c.militia_max()
        c.production = game._default_production(c)
    game.factions[f].conquests += 1
    names = ", ".join(c.name for c in country)
    _announce(game, f, CARDS["coup"], f"il governo cambia: {names} passano con {game.factions[f].name}!", cell, None,
              public=True)
    game._dirty()
    return "ok"


def _spy(game, f, cell, target) -> str:
    game.factions[f].effects["spy"] = [target, game.turn + 1]
    game._dirty()
    for line in intel(game, target):
        game.log(f"◈ {line}", [f], "info", "", f)
    game.log(f"◈ Spionaggio su {game.factions[target].name}: rapporto completo qui sopra; "
             "vedi le sue unità fino al tuo prossimo turno.", [f], "alert", "spy", f)
    return "ok"


def intel(game: "Game", t: int) -> list[str]:
    """The spy's report on faction ``t``."""
    fac = game.factions[t]
    units = game.units_of(t)
    kinds = {}
    for u in units:
        kinds[u.type.name] = kinds.get(u.type.name, 0) + 1
    building = {}
    for c in game.cities_of(t):
        name = UNIT_TYPES[c.production].name if c.production in UNIT_TYPES else "armi speciali"
        building[name] = building.get(name, 0) + 1
    army = ", ".join(f"{n} {k.lower()}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
    plans = ", ".join(f"{k.lower()} in {n} città" for k, n in sorted(building.items(), key=lambda kv: -kv[1])[:3])
    capitals = [c.name for c in game.cities_of(t) if c.capital]
    return [
        f"Rapporto su {fac.name}: {len(game.cities_of(t))} città, {len(units)} unità.",
        f"Esercito: {army or 'nessuno'}.",
        f"Testate nucleari: {fac.warheads} · armi chimiche: {fac.chemicals} · carte in mano: {len(fac.cards)}.",
        f"Produzione: {plans or 'ferma'}.",
        f"Capitali: {', '.join(capitals) or 'nessuna'}.",
    ]


def _sabotage(game, f, cell, target) -> str:
    city = game.city(cell)
    city.progress = 0.0
    city.unrest = max(city.unrest, 3)
    _announce(game, f, CARDS["sabotage"], f"esplosioni nelle fabbriche di {city.name}.", cell, city.owner)
    return "ok"


def _shield(game, f, cell, target) -> str:
    game.factions[f].effects["shield"] = game.turn + 5
    _announce(game, f, CARDS["shield"], "difesa antimissile potenziata per 6 turni.", None, None)
    return "ok"


def _detente(game, f, cell, target) -> str:
    before = game.doomsday
    game.doomsday = min(game.scenario.doomsday, game.doomsday + 3)
    game.log(f"♠ {game.factions[f].name} convoca un vertice di pace: l'Orologio dell'Apocalisse "
             f"passa da {before} a {game.doomsday} minuti.", None, "alert", "truce", f)
    return "ok"


EFFECTS = {"plan": _plan, "mobilize": _mobilize, "reinforce": _reinforce, "defect": _defect,
           "commando": _commando, "revolt": _revolt, "coup": _coup, "spy": _spy,
           "sabotage": _sabotage, "shield": _shield, "detente": _detente}
