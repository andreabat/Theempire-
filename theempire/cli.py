"""Command line entry point: ``python -m theempire`` or ``theempire``."""

from __future__ import annotations

import argparse
import curses
import locale
import sys
import time
from pathlib import Path

from theempire import __version__
from theempire.ai import AI
from theempire.game import DIFFICULTY, Game
from theempire.scenarios import SCENARIOS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="theempire",
        description="Gioco di strategia globale a turni nel terminale "
                    "(ispirato a Theatre Europe ed Empire).")
    p.add_argument("--scenario", choices=sorted(SCENARIOS), help="scenario (salta il menu)")
    p.add_argument("--faction", action="append", default=[],
                   help="fazione umana; ripeti per l'hot-seat (es. --faction west --faction east)")
    p.add_argument("--difficulty", choices=list(DIFFICULTY), default="normale")
    p.add_argument("--seed", type=int, default=None, help="seme casuale per partite ripetibili")
    p.add_argument("--load", type=Path, nargs="?", const=Path.home() / ".theempire" / "save.json",
                   help="carica una partita salvata")
    p.add_argument("--save", type=Path, default=Path.home() / ".theempire" / "save.json",
                   help="file di salvataggio")
    p.add_argument("--autoplay", type=int, metavar="TURNI",
                   help="partita IA contro IA senza interfaccia, per TURNI turni")
    p.add_argument("--list", action="store_true", help="elenca scenari e fazioni")
    p.add_argument("--version", action="version", version=f"theempire {__version__}")
    return p.parse_args(argv)


def list_scenarios() -> None:
    for s in SCENARIOS.values():
        print(f"{s.key:8s} {s.name}")
        print(f"         {s.description}")
        for f in s.factions:
            print(f"           --faction {f.key:6s} {f.name}")


def autoplay(args: argparse.Namespace) -> int:
    g = Game(args.scenario or "ww3", difficulty=args.difficulty, seed=args.seed)
    t0 = time.time()
    while not g.over and g.turn <= args.autoplay:
        AI(g, g.current).play()
        g.end_turn()
        if g.current == 0 and (g.turn % 10 == 0 or g.over):
            parts = [f"{f.key} {len(g.cities_of(f.idx))}c/{len(g.units_of(f.idx))}u/{f.warheads}☢"
                     for f in g.factions]
            print(f"turno {g.turn:3d}  orologio {g.doomsday:2d}'  " + "  ".join(parts)
                  + f"  neutrali {len(g.cities_of(None))}c  ({time.time() - t0:.0f}s)", flush=True)
    for e in g.events[-12:]:
        print(f"[{e.turn}] {e.text}")
    if g.over:
        winner, reason = g.over
        print("FINE:", reason, g.factions[winner].name if winner is not None else "nessuno")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        list_scenarios()
        return 0
    if args.autoplay:
        return autoplay(args)
    locale.setlocale(locale.LC_ALL, "")
    if args.scenario and args.faction:
        valid = {f.key for f in SCENARIOS[args.scenario].factions}
        bad = [f for f in args.faction if f not in valid]
        if bad:
            print(f"Fazione sconosciuta per {args.scenario}: {', '.join(bad)} "
                  f"(valide: {', '.join(sorted(valid))})", file=sys.stderr)
            return 2

    def run(scr) -> None:
        from theempire.ui import UI, setup_menu
        if args.load:
            game = Game.load_file(args.load)
        elif args.scenario:
            humans = tuple(args.faction) or (SCENARIOS[args.scenario].factions[0].key,)
            game = Game(args.scenario, humans=humans, difficulty=args.difficulty, seed=args.seed)
        else:
            choice = setup_menu(scr)
            if choice is None:
                return
            if "load" in choice:
                if not choice["load"].exists():
                    return
                game = Game.load_file(choice["load"])
            else:
                game = Game(choice["scenario"], humans=choice["humans"],
                            difficulty=choice["difficulty"], seed=args.seed)
        UI(scr, game, args.save).run()

    curses.wrapper(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
