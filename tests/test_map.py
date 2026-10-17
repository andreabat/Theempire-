"""The world map: the Mediterranean must be navigable end to end, and the
mouse can drag (pan) the map."""

import curses

from theempire.game import Game
from theempire.scenarios import SCENARIOS
from theempire.ui import UI
from theempire.world import load_world


def _cell(w, lon: float, lat: float) -> int:
    x = int(round(lon - w.lon0)) % w.width
    y = int(round((w.lat0 - lat) / w.dlat))
    return y * w.width + x


def _sea_path(w, start, goal) -> int | None:
    """Shortest number of sea steps between two cells, or None if landlocked."""
    from collections import deque
    queue, dist = deque([start]), {start: 0}
    while queue:
        c = queue.popleft()
        if c == goal:
            return dist[c]
        for n in w.neighbors[c]:
            if n not in dist and not w.land[n]:
                dist[n] = dist[c] + 1
                queue.append(n)
    return None


def test_gibraltar_to_levant_is_navigable():
    w = load_world()
    steps = _sea_path(w, _cell(w, -6, 37), _cell(w, 31, 35))
    assert steps is not None and steps > 0


def test_west_med_meets_the_atlantic():
    w = load_world()
    steps = _sea_path(w, _cell(w, -20, 37), _cell(w, 5, 39))
    assert steps is not None and steps > 0


def test_black_sea_still_open():
    w = load_world()
    steps = _sea_path(w, _cell(w, 30, 43), _cell(w, 34, 45))
    assert steps is not None and steps > 0


def test_mediterranean_cities_survive():
    w = load_world()
    for name, lon, lat in (("Algiers", 3, 35), ("Tunis", 10, 37),
                           ("Valletta", 14, 35), ("Tripoli", 13, 33),
                           ("Athens", 23, 37), ("Rabat", -7, 35)):
        city = next(c for c in w.sites if c.name == name)
        assert w.land[city.cell] and not (city.cell == _cell(w, lon, lat) is None)


class _FakeScr:
    def getmaxyx(self):
        return 50, 200


def _ui_with_curses(monkeypatch) -> UI:
    ui = object.__new__(UI)
    ui.scr = _FakeScr()
    ui.w = load_world()
    session = type("Session", (), {})()
    session.game = Game("ww3", humans=(SCENARIOS["ww3"].factions[0].key,), seed=1,
                        world=ui.w)
    ui.session = session
    ui.viewer = 0
    ui.view_x = 100
    ui.view_y = 10
    ui.cursor = 0
    ui.mode = "normal"
    ui._pan = None
    ui._pan_view = None
    ui.active_id = None

    def fake_getmouse():
        return ("", ui.mx, ui.my, 0, ui.state)
    monkeypatch.setattr(curses, "getmouse", fake_getmouse)
    return ui


def test_mouse_drag_pans(monkeypatch):
    ui = _ui_with_curses(monkeypatch)
    ui.mx, ui.my, ui.state = 20, 10, curses.BUTTON1_PRESSED
    ui.mouse()                      # press: remembers where the drag started
    assert ui._pan == (20, 10)
    ui.mx, ui.my = 26, 12           # drag right and down
    ui.state = curses.BUTTON1_PRESSED
    ui.mouse()
    assert ui.view_x == 94          # the map follows the hand (opposite)
    assert ui.view_y == 8
    ui.mx, ui.my = 26, 12
    ui.state = curses.BUTTON1_RELEASED
    ui.mouse()
    assert ui._pan is None
    assert ui.cursor == 19 * ui.w.width + 120  # cursor lands on the release cell


def test_mouse_click_still_moves_cursor(monkeypatch):
    ui = _ui_with_curses(monkeypatch)
    ui.mx, ui.my, ui.state = 20, 10, curses.BUTTON1_PRESSED
    ui.mouse()
    ui.mx, ui.my = 21, 11           # tiny movement = a click
    ui.state = curses.BUTTON1_RELEASED
    ui.mouse()
    assert ui._pan is None
    assert ui.view_x == 100         # no pan for a click
    assert ui.cursor == 20 * ui.w.width + 121