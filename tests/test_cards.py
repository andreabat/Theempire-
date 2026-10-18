"""Futurisiko-style cards: earning them, every effect, secrecy online."""

import random

import pytest

from theempire import cards, commands
from theempire.game import Game
from theempire.world import load_world


class Lucky(random.Random):
    """Every chance roll succeeds (and every fight is won)."""

    def random(self):
        return 0.0


class Unlucky(random.Random):
    def random(self):
        return 0.999


@pytest.fixture(scope="module")
def world():
    return load_world()


def game(world, rng=None):
    g = Game("ww3", humans=("west",), seed=9, world=world)
    if rng is not None:
        g.rng = rng
    return g


def give(g, f, key):
    g.factions[f].cards.append(key)


def free_land(g, near=None):
    w = g.world
    for i in range(w.size):
        if w.land[i] and g.city(i) is None and i not in g.at and \
                (near is None or w.dist(i, near) == 1):
            return i
    raise AssertionError


def test_deck_and_hand_limit(world):
    g = game(world)
    assert len(g.deck) + sum(len(f.cards) for f in g.factions) == sum(c.copies for c in cards.CARDS.values())
    for _ in range(cards.HAND_LIMIT + 3):
        cards.draw(g, 0, "test")
    assert len(g.factions[0].cards) == cards.HAND_LIMIT


def test_conquest_earns_a_card(world):
    g = game(world)
    before = len(g.factions[0].cards)
    g.factions[0].conquests = 1
    g.end_turn()
    assert len(g.factions[0].cards) == before + 1
    assert g.factions[0].conquests == 0


def test_briefing_every_few_turns(world):
    g = game(world)
    g.turn = cards.BRIEFING_EVERY
    g.current = 0
    before = len(g.factions[0].cards)
    g.begin_turn()
    assert len(g.factions[0].cards) == before + 1


def test_cannot_play_a_card_you_do_not_hold(world):
    g = game(world)
    assert commands.apply(g, 0, {"op": "card", "card": "plan"}) == "illegal"
    give(g, 0, "plan")
    assert commands.apply(g, 1, {"op": "card", "card": "plan"}) == "notyourturn"


def test_plan_and_mobilize(world):
    g = game(world)
    c = g.cities_of(0)[0]
    rate = g.production_rate(c)
    give(g, 0, "plan")
    assert commands.apply(g, 0, {"op": "card", "card": "plan"}) == "ok"
    assert g.production_rate(c) == pytest.approx(rate * 1.5)
    g.turn += 3
    assert g.production_rate(c) == pytest.approx(rate)
    give(g, 0, "mobilize")
    before = c.progress
    cards.play(g, 0, "mobilize")
    assert c.progress == pytest.approx(before + g.production_rate(c))


def test_reinforce(world):
    g = game(world)
    c = g.cities_of(0)[0]
    n = len(g.units_at(c.cell))
    give(g, 0, "reinforce")
    assert cards.play(g, 0, "reinforce", cell=g.cities_of(1)[0].cell) == "card_own_city"
    assert cards.play(g, 0, "reinforce", cell=c.cell) == "ok"
    assert len(g.units_at(c.cell)) == n + 3


def test_defection_and_commando(world):
    g = game(world, Lucky())
    spot = free_land(g)
    enemy = g.create_unit("A", 1, spot)
    give(g, 0, "defect")
    assert cards.play(g, 0, "defect", cell=spot) == "card_no_enemy_unit"     # not seen
    mine = g.create_unit("I", 0, free_land(g, near=spot))
    assert cards.play(g, 0, "defect", cell=spot) == "ok"
    assert enemy.owner == 0
    victim = g.create_unit("A", 1, free_land(g, near=mine.cell))
    give(g, 0, "commando")
    assert cards.play(g, 0, "commando", cell=victim.cell) == "ok"
    assert victim.id not in g.units


def test_failed_attempt_spends_the_card(world):
    g = game(world, Unlucky())
    spot = free_land(g)
    enemy = g.create_unit("A", 1, spot)
    g.create_unit("I", 0, free_land(g, near=spot))
    give(g, 0, "defect")
    assert cards.play(g, 0, "defect", cell=spot) == "failed"
    assert enemy.owner == 1 and "defect" not in g.factions[0].cards


def test_revolt(world):
    g = game(world, Lucky())
    city = next(c for c in g.cities_of(1) if not c.capital and c.size <= 2)
    give(g, 0, "revolt")
    assert cards.play(g, 0, "revolt", cell=city.cell) == "ok"
    assert city.owner is None                                    # no troops of ours nearby
    city2 = next(c for c in g.cities_of(1) if not c.capital and c.size <= 2)
    land = next(n for n in g.world.neighbors[city2.cell] if g.world.land[n] and g.city(n) is None)
    for u in g.units_at(land):
        g.kill(u)
    g.create_unit("I", 0, land)
    give(g, 0, "revolt")
    assert cards.play(g, 0, "revolt", cell=city2.cell) == "ok"
    assert city2.owner == 0
    assert all(u.owner == 0 for u in g.units_at(city2.cell))


def test_coup(world):
    g = game(world, Lucky())
    city = next(c for c in g.cities if c.owner is None
                and len([x for x in g.cities if x.iso == c.iso]) == 2
                and all(x.owner is None for x in g.cities if x.iso == c.iso))
    give(g, 0, "coup")
    assert cards.play(g, 0, "coup", cell=city.cell) == "card_no_friends"   # nobody of ours nearby
    g.create_unit("I", 0, free_land(g, near=city.cell))
    assert cards.play(g, 0, "coup", cell=city.cell) == "ok"
    assert all(c.owner == 0 for c in g.cities if c.iso == city.iso)


def test_spy_reveals_the_enemy(world):
    g = game(world)
    far = [u for u in g.units.values() if u.owner == 1 and u.cell not in g.visible(0)]
    assert far
    give(g, 0, "spy")
    assert cards.play(g, 0, "spy", target=1) == "ok"
    assert all(u.cell in g.visible(0) for u in far)
    assert any(e.text.startswith("◈ Rapporto") for e in g.events)


def test_sabotage_shield_detente(world):
    g = game(world, Lucky())
    city = max(g.cities_of(1), key=lambda c: c.size)
    city.progress = 9
    give(g, 0, "sabotage")
    assert cards.play(g, 0, "sabotage", cell=city.cell) == "ok"
    assert city.progress == 0 and city.unrest >= 3
    give(g, 1, "shield")
    cards.play(g, 1, "shield")
    assert cards.active(g, 1, "shield")
    g.doomsday = 4
    give(g, 0, "detente")
    cards.play(g, 0, "detente")
    assert g.doomsday == 7


def test_hands_are_secret_online(world):
    g = game(world)
    give(g, 1, "coup")
    give(g, 0, "spy")
    view = commands.view_for(g, 0)
    assert view["factions"][0]["cards"] == g.factions[0].cards
    assert view["factions"][1]["cards"] == ["?"] * len(g.factions[1].cards)
    assert set(view["deck"]) <= {"?"}


def test_cards_survive_save_and_load(world, tmp_path):
    g = game(world)
    give(g, 0, "plan")
    cards.play(g, 0, "plan")
    give(g, 0, "spy")
    path = tmp_path / "s.json"
    g.save_file(path)
    h = Game.load_file(path)
    assert h.factions[0].cards == g.factions[0].cards
    assert cards.active(h, 0, "plan") and h.deck == g.deck and h.discard == g.discard


def test_revolt_works_in_minor_capitals_but_not_the_seat(world):
    g = Game("coldwar", humans=("nato",), seed=9, world=world)
    g.rng = Lucky()
    seat = cards.seat(g, 1)
    assert seat.name == "Moscow"
    give(g, 0, "revolt")
    assert cards.play(g, 0, "revolt", cell=seat.cell) == "card_seat"
    minor = next(c for c in g.cities_of(1) if c.capital and c.size <= 2 and c is not seat)
    assert cards.play(g, 0, "revolt", cell=minor.cell) == "ok"     # e.g. a Warsaw Pact capital
    assert minor.owner is None
    big = next((c for c in g.cities_of(1) if c.size == 3 and c is not seat), None)
    if big is not None:
        give(g, 0, "revolt")
        assert cards.play(g, 0, "revolt", cell=big.cell) == "card_too_big"
    give(g, 0, "revolt")
    assert cards.play(g, 0, "revolt", cell=g.cities_of(0)[0].cell) == "card_not_enemy_city"


def test_tutorial_tirana_is_the_seat(world):
    g = Game("tutorial", humans=("ita",), seed=1, world=world)
    assert cards.seat(g, 1).name == "Tirana"


def test_conquests_earn_cards_only_by_chance():
    from theempire import cards
    from theempire.game import Game
    from theempire.world import load_world

    class Fixed(random.Random):
        def __init__(self, value):
            super().__init__(0)
            self.value = value

        def random(self):
            return self.value

    g = Game("ww3", seed=1, world=load_world())
    small = next(c for c in g.cities if c.size == 1 and not c.capital)
    capital = next(c for c in g.cities if c.capital)
    assert cards.conquest_weight(small) == 1 and cards.conquest_weight(capital) == 3
    fac = g.factions[0]
    fac.cards.clear()
    fac.conquests, g.rng = 1, Fixed(0.3)          # a small city: 20%, the roll is 30%: no card
    cards.end_of_turn(g, 0)
    assert fac.cards == [] and "probabilità 20%" in g.events[-1].text
    fac.conquests, g.rng = 3, Fixed(0.5)          # a capital: 60%
    cards.end_of_turn(g, 0)
    assert len(fac.cards) == 1
    fac.conquests, g.rng = 10, Fixed(0.85)        # never more than 80%
    cards.end_of_turn(g, 0)
    assert len(fac.cards) == 1
