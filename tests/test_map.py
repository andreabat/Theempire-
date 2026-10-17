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


def test_no_duplicate_city_names():
    """Regressione: il bollettino "conquista London" era ambiguo perché due città
    reali diverse (Londra GB e London, Ontario) condividevano lo stesso nome."""
    w = load_world()
    names = [c.name for c in w.sites]
    dup = {n for n in names if names.count(n) > 1}
    assert not dup, f"nomi città duplicati: {sorted(dup)}"


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

def test_mouse_drag_without_motion_reports(monkeypatch):
    # the terminal sent only press and release: still a drag
    ui = _ui_with_curses(monkeypatch)
    ui.mx, ui.my, ui.state = 20, 10, curses.BUTTON1_PRESSED
    ui.mouse()
    ui.mx, ui.my, ui.state = 26, 12, curses.BUTTON1_RELEASED
    ui.mouse()
    assert (ui.view_x, ui.view_y) == (94, 8)
    assert ui._pan is None


def test_mouse_drag_when_the_press_is_lost(monkeypatch):
    # a burst of events: ncurses dropped the press, only motions arrive
    ui = _ui_with_curses(monkeypatch)
    ui.mx, ui.my, ui.state = 20, 10, curses.REPORT_MOUSE_POSITION
    ui.mouse()
    ui.mx, ui.my = 26, 12
    ui.mouse()
    assert (ui.view_x, ui.view_y) == (94, 8)
    ui.state = curses.BUTTON1_RELEASED
    ui.mouse()
    assert ui._pan is None


def test_click_on_a_panel_label_presses_its_key(monkeypatch):
    ui = _ui_with_curses(monkeypatch)
    pressed = []
    ui.handle = pressed.append
    ui.hotspots = [(4, 170, 190, "K")]       # "Carte ♠ 0/5 (K)" in the panel
    ui.mx, ui.my, ui.state = 175, 4, curses.BUTTON1_PRESSED
    ui.mouse()
    assert pressed == []                      # nothing happens on the press
    ui.state = curses.BUTTON1_RELEASED
    ui.mouse()
    assert pressed == [ord("K")]


def test_stray_release_does_not_click_the_map(monkeypatch):
    # the release of a click that closed a menu must not move units
    ui = _ui_with_curses(monkeypatch)
    clicked = []
    ui.click = clicked.append
    ui.hotspots = []
    ui.mx, ui.my, ui.state = 20, 10, curses.BUTTON1_RELEASED
    ui.mouse()
    assert clicked == []


def test_zoom_maps_clicks_to_cells(monkeypatch):
    ui = _ui_with_curses(monkeypatch)
    ui.zoom = 2                                     # a cell is 4×2 characters
    assert ui.view_size() == ((200 - 36 - 1) // 4, (50 - 6 - 2) // 2)
    assert ui._cell_at(9, 4) == (10 + 1) * ui.w.width + 100 + 2
    ui.mx, ui.my, ui.state = 40, 20, curses.BUTTON1_PRESSED
    ui.mouse()
    ui.mx, ui.state = 48, curses.BUTTON1_RELEASED   # 8 characters = 2 cells
    ui.mouse()
    assert ui.view_x == 98


def test_zoomed_coastline_is_magnified():
    from theempire.ui import zoom_braille
    left_column = chr(0x2800 + 0x01 + 0x02 + 0x04 + 0x40)   # ⡇
    assert zoom_braille(left_column, 0, 0, 2, 1) == "⣿"      # doubled: fills the left char
    assert zoom_braille(left_column, 1, 0, 2, 1) == " "      # and nothing on the right
    assert zoom_braille("⣿", 1, 1, 4, 2) == "⣿"
