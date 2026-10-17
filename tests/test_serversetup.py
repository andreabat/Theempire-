"""The setup screen of --serve: the configuration it builds."""

from theempire import cli
from theempire.serversetup import Config, _rows


def test_default_is_a_full_house_with_the_web():
    c = Config()
    assert c.seats() == ["west", "east", "china"]
    assert c.problem() is None
    assert c.argv() == ["--serve", "7777", "--scenario", "ww3", "--faction", "west",
                        "--faction", "east", "--faction", "china", "--web", "8080"]


def test_changing_scenario_resets_the_seats():
    c = Config()
    scenario = next(r for r in _rows(c) if r.label == "Scenario")
    scenario.change(1)
    assert c.scenario == "coldwar" and c.seats() == ["nato", "pact"]


def test_options_reach_the_command_line():
    c = Config(scenario="coldwar")
    c.humans["pact"] = False
    c.play, c.name = "nato", "Anna"
    c.objectives = c.world_events = False
    c.turn_time, c.web = 90, False
    c.password = "segreta"
    argv = c.argv()
    assert "--senza-obiettivi" in argv and "--senza-eventi" in argv
    assert argv[argv.index("--play") + 1] == "nato" and "--web" not in argv
    assert "segreta" not in c.command()              # never printed
    args = cli.parse_args(argv + ["--password", "x"])
    assert args.scenario == "coldwar" and args.faction == ["nato"] and args.turn_time == 90
    assert args.objectives is False and args.world_events is False


def test_problems_are_explained():
    c = Config()
    for k in c.humans:
        c.humans[k] = False
    assert "almeno un posto" in c.problem()
    c.humans["west"] = True
    c.web_port = c.port
    assert "diversa" in c.problem()


def test_playing_seat_must_be_human():
    c = Config()
    c.play = "east"
    toggle = next(r for r in _rows(c) if r.label.strip() == "Unione Eurasiatica")
    toggle.change(1)                                 # east goes to the AI
    assert c.play == ""


def test_language_row_switches_at_once(tmp_path, monkeypatch):
    from theempire import i18n
    monkeypatch.setattr(i18n, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setenv("THEEMPIRE_LANG", "it")
    i18n.set_language("it")
    c = Config()
    try:
        lang = next(r for r in _rows(c) if r.label == "Lingua")
        assert lang.value == "Italiano" and "--lang" not in c.argv()
        lang.change(1)                               # → English, saved for next time
        assert i18n.language() == "en" and i18n._saved() == "en"
        assert c.argv()[-2:] == ["--lang", "en"]
    finally:
        i18n.set_language("it")
