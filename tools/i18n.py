"""Keep the translations in step with the code.

    python3 tools/i18n.py check        # what is missing or broken, per language
    python3 tools/i18n.py update       # add the new texts (empty) to every catalogue

The Italian text inside tr(), Msg() and N() calls is the key; the
catalogues are theempire/locales/<lang>.json. The web page keeps its own
small table inside theempire/assets/web/index.html.
"""

from __future__ import annotations

import ast
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "theempire"
sys.path.insert(0, str(ROOT))
from theempire.i18n import DEFAULT, LANGS, LOCALES  # noqa: E402

CALLS = {"tr", "N", "Msg"}


def keys() -> dict[str, str]:
    """Every key in the code -> where it was found first."""
    found: dict[str, str] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else \
                node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name not in CALLS:
                continue
            arg = node.args[0]
            where = f"{path.relative_to(ROOT)}:{node.lineno}"
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.setdefault(arg.value, where)
            elif isinstance(arg, ast.JoinedStr):
                raise SystemExit(f"{where}: f-string inside {name}(): use named placeholders")
    return found


def fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def check(update: bool = False) -> int:
    code = keys()
    problems = 0
    for lang in LANGS:
        if lang == DEFAULT:
            continue
        path = LOCALES / f"{lang}.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        missing = [k for k in code if not data.get(k)]
        unused = [k for k in data if k not in code]
        broken = [k for k, v in data.items() if v and k in code and fields(k) != fields(v)]
        if update:
            for k in code:
                data.setdefault(k, "")
            path.write_text(json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=1)
                            + "\n", encoding="utf-8")
        print(f"{lang}: {len(code) - len(missing)}/{len(code)} tradotti, "
              f"{len(missing)} mancanti, {len(broken)} con segnaposto diversi, {len(unused)} inutilizzati")
        for k in broken[:10]:
            print(f"   segnaposto: {k!r}")
        problems += len(missing) + len(broken)
    return 1 if problems else 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(check(update=command == "update"))
