"""Board-game rules: regions with a bonus, secret objectives, world events."""

import pytest

from theempire import commands, events, missions, regions
from theempire.game import Game
from theempire.world import load_world


@pytest.fixture(scope="module")
def world():
    return load_world()


def test_every_city_has_a_region(world):
    g = Game("ww3", seed=1, world=world)
    keys = regions.city_regions(g)
    assert len(keys) == len(g.cities) and set(keys) <= set(regions.REGIONS)
    rome = next(c for c in g.cities if c.name == "Rome")
    assert keys[rome.id] == "weu"
    sizes = {k: regions.bonus_of(g, k) for k in regions.REGIONS}
    assert min(sizes.values()) == regions.BONUS_MIN and max(sizes.values()) == regions.BONUS_MAX


def test_holding_a_region_raises_production(world):
    g = Game("ww3", seed=1, world=world)
    city = g.cities_of(0)[0]
    before = g.production_rate(city)
    for c in regions.cities_in(g, "naf"):
        c.owner = 0
    regions.update(g)
    assert g.region_holders["naf"] == 0
    assert any("Nord Africa" in e.text for e in g.events)          # announced
    assert g.production_rate(city) == pytest.approx(before * (1 + regions.bonus_of(g, "naf")))
    g.cities[regions.cities_in(g, "naf")[0].id].owner = 1
    regions.update(g)
    assert g.region_holders["naf"] is None


def test_every_faction_gets_a_secret_objective(world):
    for scenario in ("ww3", "coldwar", "empire"):
        g = Game(scenario, seed=3, world=world)
        for f in g.factions:
            assert f.mission["kind"] in ("regions", "eliminate", "cities", "capitals")
            assert missions.text(g, f.idx) and missions.progress(g, f.idx)
            assert not missions.done(g, f.idx)
    tutorial = Game("tutorial", seed=3, world=world)
    assert not any(f.mission for f in tutorial.factions)


def test_objective_wins_the_game(world):
    g = Game("ww3", seed=3, world=world)
    g.factions[0].mission = {"kind": "regions", "regions": ["naf", "cam"]}
    for key in ("naf", "cam"):
        for c in regions.cities_in(g, key):
            c.owner = 0
    g.end_turn()
    assert g.over == (0, "mission")


def test_objective_is_secret_online(world):
    g = Game("ww3", seed=3, world=world)
    view = commands.view_for(g, 0)
    assert view["factions"][0]["mission"] == g.factions[0].mission
    assert view["factions"][1]["mission"] == {"kind": "secret"}
    restored = Game.from_dict(view, world)
    assert missions.text(restored, 1) == ""


def test_elimination_by_someone_else_changes_the_objective(world):
    g = Game("ww3", seed=3, world=world)
    g.factions[0].mission = {"kind": "eliminate", "target": 2}
    g.eliminate(2, by=1)
    assert g.factions[0].mission["kind"] == "cities"
    g.factions[1].mission = {"kind": "eliminate", "target": 0}
    g.eliminate(0, by=1)
    assert missions.done(g, 1)


def test_world_events_come_and_go(world):
    g = Game("ww3", seed=3, world=world)
    assert 1 < g.next_event <= 1 + events.EVERY[1]
    g.next_event = g.turn + 1
    g.world_effects.clear()
    g._new_round()
    assert any(e.level == "world" for e in g.events)
    assert g.next_event > g.turn
    # an effect: the oil crisis halves the moves of ships and aircraft
    g.world_effects = {"oil": g.turn}
    g.begin_turn()
    planes = [u for u in g.units_of(g.current) if u.kind == "F"]
    assert planes and all(u.moves == 4 for u in planes)
    saved = Game.from_dict(g.to_dict(), world)
    assert saved.world_effects == {"oil": g.turn} and saved.next_event == g.next_event
    g.turn += 1
    g.next_event = 10 ** 6
    g._new_round()
    assert "oil" not in g.world_effects


def test_every_event_can_happen(world):
    for key, event in events.EVENTS.items():
        g = Game("ww3", seed=5, world=world)
        g.doomsday -= 1                  # room for the thaw
        if key == "uprising":            # only an ungarrisoned city rises
            city = next(c for c in g.cities_of(0) if not c.capital)
            for u in g.units_at(city.cell):
                g.kill(u)
        if key == "hurricane":           # it needs ships at sea
            sea = next(i for i in range(world.size) if not world.land[i] and i not in g.at)
            ship = g.create_unit("D", 0, sea)
        detail = event.act(g)
        assert detail, key
        if key == "hurricane":
            assert ship.hp == ship.type.hp - 1


def test_capitals_objective_counts_rival_capitals(world):
    g = Game("coldwar", seed=3, world=world)
    g.factions[0].mission = {"kind": "capitals", "count": 2}
    neutral = next(c for c in g.cities if c.capital and c.owner is None)
    neutral.owner = 0                               # a neutral capital does not count
    assert missions.progress(g, 0) == "0/2 capitali nemiche"
    enemy = [c for c in g.cities if c.capital and c.founder == 1][:2]
    for c in enemy:
        c.owner = 0
    assert missions.done(g, 0)
