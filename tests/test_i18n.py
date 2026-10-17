"""Languages: the translation API and the completeness of the catalogues."""

import importlib.util
import string
from pathlib import Path

import pytest

from theempire import i18n
from theempire.game import Game
from theempire.world import load_world

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def italian_again():
    yield
    i18n.set_language("it")


def test_messages_are_translated_by_the_reader(monkeypatch):
    monkeypatch.setitem(i18n._catalogs, "en", {"{faction} conquista {city}.": "{faction} takes {city}.",
                                              "Alleanza Atlantica": "Atlantic Alliance"})
    msg = i18n.Msg("{faction} conquista {city}.", faction="Alleanza Atlantica", city="Rome")
    assert msg.render("it") == "Alleanza Atlantica conquista Rome."
    assert msg.render("en") == "Atlantic Alliance takes Rome."      # names translated, cities not
    saved = msg.to_json()
    assert i18n.render(saved, "en") == "Atlantic Alliance takes Rome."
    assert i18n.tr("Testo senza traduzione", "en") == "Testo senza traduzione"


def test_a_broken_translation_falls_back_to_italian(monkeypatch):
    monkeypatch.setitem(i18n._catalogs, "en", {"{n} città": "{count} cities"})
    assert i18n.tr("{n} città", "en", n=3) == "3 città"


def test_log_keeps_the_message_for_every_reader():
    g = Game("ww3", seed=1, world=load_world())
    g.log(i18n.Msg("Prova {x}", x=1))
    e = g.events[-1]
    assert e.text == "Prova 1" and e.msg == ["Prova {x}", {"x": 1}]
    assert Game.from_dict(g.to_dict(), load_world()).events[-1].shown("it") == "Prova 1"


def test_language_detection(monkeypatch, tmp_path):
    monkeypatch.setattr(i18n, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.delenv("THEEMPIRE_LANG", raising=False)
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.detect() == "de"
    i18n.save_language("pt")
    assert i18n.detect() == "pt"
    assert i18n.detect("fr") == "fr"
    monkeypatch.setenv("THEEMPIRE_LANG", "es")
    assert i18n.detect() == "es"


def _tool():
    spec = importlib.util.spec_from_file_location("i18n_tool", ROOT / "tools" / "i18n.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


@pytest.mark.parametrize("lang", [code for code in i18n.LANGS if code != i18n.DEFAULT])
def test_every_text_is_translated(lang):
    keys = _tool().keys()
    catalog = i18n.catalog(lang)
    missing = [k for k in keys if not catalog.get(k)]
    assert not missing, f"{lang}: {len(missing)} testi senza traduzione, es. {missing[:3]}"
    fields = lambda text: {f for _, f, _, _ in string.Formatter().parse(text) if f}  # noqa: E731
    broken = [k for k in keys if fields(k) != fields(catalog[k])]
    assert not broken, f"{lang}: segnaposto diversi in {broken[:3]}"
