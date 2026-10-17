"""The tutorial scenario and its instructor."""

import random

from theempire import cards, commands
from theempire.audio import EscapeAudio
from theempire.game import Game
from theempire.tutorial import STEPS, Tutorial
from theempire.world import load_world


class FakeUI:
    """Just what the instructor looks at."""

    def __init__(self, g):
        self.g = g
        self.viewer = 0
        self.mode = "normal"
        self.active = None
        self.audio = EscapeAudio(write=lambda data: None)
        self.dialogs = []

    def draw(self):
        pass

    def dialog(self, title, lines, footer=""):
        self.dialogs.append(title)
        return ord(" ")


def tutorial_game():
    g = Game("tutorial", humans=("ita",), seed=1, world=load_world())
    commands.advance(g)
    return g


def test_scenario():
    g = tutorial_game()
    assert [c.name for c in g.cities_of(1)] == ["Tirana"]
    assert "Rome" in [c.name for c in g.cities_of(0)]
    assert all(f.warheads == 0 and not f.nuclear for f in g.factions)


def test_steps_fit_the_instructor_box():
    for step in STEPS:
        lines = Tutorial.lines(step)
        assert lines and all(len(line) <= 72 for line in lines), step.title


def test_walkthrough():
    g = tutorial_game()
    ui = FakeUI(g)
    t = Tutorial(ui)
    t.start()
    assert t.step.title == "Guardarsi intorno"       # the welcome is read and passed
    t.update()
    assert t.step.title == "Guardarsi intorno"       # nothing done yet
    ui.mode = "overview"
    t.update()
    assert t.step.title == "Prendere il comando di un'unità"
    ui.mode = "normal"
    u = next(x for x in g.units_of(0) if x.kind == "A")
    ui.active = u
    t.update()
    assert t.step.title == "Muovere"
    step = next(n for n in g.world.neighbors[u.cell] if g.classify(u, n) == "move")
    g.move(u, step)
    t.update()
    assert t.step.title == "Ordini di marcia"
    t.goto_given = True
    t.update()
    assert t.step.title == "La produzione"
    city = g.cities_of(0)[0]
    commands.apply(g, 0, {"op": "produce", "city": city.id, "key": "I"})
    t.update()
    assert t.step.title == "Le direttive"
    commands.apply(g, 0, {"op": "directive", "name": "land"})
    t.update()
    assert t.step.title == "Fine del turno"
    commands.apply(g, 0, {"op": "end_turn"})
    t.update()
    assert t.step.title == "La prima conquista"
    neutral = next(c for c in g.cities if c.owner is None)
    neutral.owner = 0
    t.update()
    assert t.step.title == "Disordini e carte"
    assert "spy" in g.factions[0].cards              # the instructor's gift
    assert cards.play(g, 0, "spy", target=1) == "ok"
    t.update()
    assert t.step.title == "Obiettivo segreto e regioni"
    assert g.factions[0].mission == {"kind": "eliminate", "target": 1}
    t.seen_objectives = True                         # the player pressed o
    t.update()
    # the world event is shown and read, two explanations follow, then the
    # final objective waits
    assert any(e.level == "world" for e in g.events) and "boom" in g.world_effects
    assert t.step.title == "Obiettivo finale: Tirana"
    assert "reinforce" in g.factions[0].cards        # the instructor's second gift
    assert "✔ Ben fatto!" in ui.dialogs


def test_taking_tirana_wins():
    g = tutorial_game()
    g.rng = type("Lucky", (random.Random,), {"random": lambda self: 0.0})()
    tirana = g.cities_of(1)[0]
    for u in list(g.units_at(tirana.cell)):
        g.kill(u)
    for u in list(g.units_of(1)):
        g.kill(u)
    land = next(n for n in g.world.neighbors[tirana.cell] if g.world.land[n] and g.city(n) is None)
    for u in g.units_at(land):
        g.kill(u)
    a = g.create_unit("A", 0, land)
    assert g.move(a, tirana.cell) == "captured"
    g.end_turn()
    assert g.over == (0, "conquest")
