"""Languages.

The game is written in Italian and the Italian text is the key of every
translation (as in gettext): ``tr("Fine turno")`` gives "End turn" in
English. The catalogues are JSON files in ``locales/`` (one per language,
Italian text -> translation), made and checked by tools/i18n.py.

* ``tr(template, **params)`` translates now, for what the interface shows.
  String parameters that are themselves in the catalogue (faction, unit,
  card, region names...) are translated too; city names are not.
* ``Msg(template, **params)`` is a sentence translated later, by whoever
  reads it: the game's log is written on the server but read by players who
  may speak different languages. It travels as [template, params].
* ``N(text)`` only marks a text for the catalogue (tables of names and
  descriptions); it is translated where it is shown.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

LANGS = {"it": "Italiano", "en": "English", "fr": "Français", "es": "Español",
         "de": "Deutsch", "pt": "Português"}
DEFAULT = "it"
LOCALES = Path(__file__).resolve().parent / "locales"
SETTINGS = Path.home() / ".theempire" / "settings.json"

_lang = DEFAULT
_catalogs: dict[str, dict[str, str]] = {}


def N(text: str) -> str:
    return text


def catalog(lang: str) -> dict[str, str]:
    if lang not in _catalogs:
        try:
            data = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _catalogs[lang] = {k: v for k, v in data.items() if isinstance(v, str) and v}
    return _catalogs[lang]


def language() -> str:
    return _lang


def set_language(lang: str | None) -> str:
    global _lang
    _lang = lang if lang in LANGS else DEFAULT
    os.environ["THEEMPIRE_LANG"] = _lang     # the web TUI's clients inherit it
    return _lang


def detect(explicit: str | None = None) -> str:
    """--lang, then THEEMPIRE_LANG, then the saved choice, then the system's."""
    if explicit in LANGS:
        return explicit
    env = os.environ.get("THEEMPIRE_LANG", "")
    if env in LANGS:
        return env
    saved = _saved()
    if saved in LANGS:
        return saved
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        code = os.environ.get(var, "")[:2].lower()
        if code in LANGS:
            return code
    return DEFAULT


def _saved() -> str:
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return data.get("lang", "") if isinstance(data, dict) else ""
    except (OSError, ValueError):
        return ""


def save_language(lang: str) -> None:
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["lang"] = lang
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def word(text, lang: str | None = None):
    """A single name or phrase in the language (unchanged if unknown)."""
    if not isinstance(text, str):
        return text
    lang = lang or _lang
    if lang == DEFAULT:
        return text
    return catalog(lang).get(text, text)


def tr(template: str, lang: str | None = None, **params) -> str:
    lang = lang or _lang
    text = word(template, lang)
    if not params:
        return text
    values = {k: _value(v, lang) for k, v in params.items()}
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return template.format(**values)    # a broken translation: fall back to Italian


def _value(v, lang: str):
    if isinstance(v, Msg):
        return v.render(lang)
    if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], dict):
        return render(v, lang)
    return word(v, lang)


class Msg:
    """A sentence to translate when it is read."""

    __slots__ = ("template", "params")

    def __init__(self, template: str, **params):
        self.template = template
        self.params = params

    def render(self, lang: str | None = None) -> str:
        return tr(self.template, lang, **self.params)

    def __str__(self) -> str:
        return self.render()

    def to_json(self) -> list:
        return [self.template, {k: v.to_json() if isinstance(v, Msg) else v
                                for k, v in self.params.items()}]


def render(msg, lang: str | None = None) -> str:
    """A message as saved ([template, params]) or a plain text, translated."""
    if isinstance(msg, Msg):
        return msg.render(lang)
    if isinstance(msg, list) and len(msg) == 2:
        return tr(msg[0], lang, **msg[1])
    return word(msg, lang)
