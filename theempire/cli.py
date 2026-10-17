"""Command line entry point: ``python -m theempire`` or ``theempire``."""

from __future__ import annotations

import argparse
import curses
import locale
import os
import sys
import time
from pathlib import Path

from theempire import __version__
from theempire.ai import AI
from theempire.game import DIFFICULTY, Game
from theempire.net import DEFAULT_PORT
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
    p.add_argument("--audio", choices=["all", "sfx", "off"],
                   help="musica ed effetti, solo effetti, o niente (predefinito: l'ultima scelta; tasto M per il menu audio)")
    p.add_argument("--muto", dest="audio", action="store_const", const="off", help="niente audio")
    online = p.add_argument_group("partita online")
    online.add_argument("--serve", type=int, nargs="?", const=DEFAULT_PORT, metavar="PORTA",
                        help=f"ospita una partita online (porta predefinita {DEFAULT_PORT}); "
                             "le fazioni date con --faction sono i posti per i giocatori, "
                             "le altre le guida l'IA")
    online.add_argument("--bind", default="0.0.0.0", help="indirizzo su cui ascoltare (server)")
    online.add_argument("--play", metavar="FAZIONE",
                        help="con --serve: gioca anche tu, da questo terminale, con FAZIONE")
    online.add_argument("--join", metavar="HOST[:PORTA]", help="entra in una partita online")
    online.add_argument("--name", default="", help="il tuo nome nella partita online")
    online.add_argument("--password", default=os.environ.get("THEEMPIRE_PASSWORD", ""),
                        help="password della partita online (anche da THEEMPIRE_PASSWORD)")
    online.add_argument("--web", type=int, nargs="?", const=8080, metavar="PORTA",
                        help="con --serve o --join: apri anche la web TUI, per giocare dal "
                             "browser (porta predefinita 8080)")
    online.add_argument("--audio-web", action="store_true", help=argparse.SUPPRESS)
    online.add_argument("--turn-time", type=int, default=0, metavar="SECONDI",
                        help="tempo massimo per turno di ogni giocatore (anche in locale)")
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


def _address(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":") if ":" in text else (text, "", "")
    return (host or "127.0.0.1"), int(port) if port else DEFAULT_PORT


def serve(args: argparse.Namespace) -> int:
    import getpass
    import threading

    from theempire.net import GameServer, RemoteSession
    save = args.save if args.save != Path.home() / ".theempire" / "save.json" else \
        Path.home() / ".theempire" / f"server-{args.serve}.json"
    if args.load:
        game = Game.load_file(args.load)
    else:
        scenario = args.scenario or "ww3"
        humans = tuple(args.faction) or tuple(f.key for f in SCENARIOS[scenario].factions)
        game = Game(scenario, humans=humans, difficulty=args.difficulty, seed=args.seed)
    log_lines: list[str] = []

    def log(line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        if args.play:
            log_lines.append(f"{stamp} {line}")
        else:
            print(f"{stamp} {line}", flush=True)

    server = GameServer(game, args.bind, args.serve, args.password, save, args.turn_time, log)
    try:
        server.listen()
    except OSError as exc:
        print(f"Impossibile aprire la porta {args.serve}: {exc}", file=sys.stderr)
        return 1
    if args.web is not None:
        gateway = _web(args, ("127.0.0.1", server.port), server.web_info, log)
        if gateway is None:
            return 1
        threading.Thread(target=gateway.serve_forever, daemon=True).start()
    if not args.play:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.save()
            server.stop()
            print("\nServer fermato, partita salvata in", save)
        return 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    name = args.name or getpass.getuser()
    session = RemoteSession("127.0.0.1", server.port, name, args.play, args.password)
    _play_online(session, args)
    server.save()
    server.stop()
    return 0


def _audio(args: argparse.Namespace):
    if args.audio_web:  # inside the web TUI: the browser plays the sounds
        from theempire.audio import EscapeAudio
        return EscapeAudio()
    from theempire.audio import Audio
    return Audio(mode=args.audio, bell=curses.beep)


def _web(args: argparse.Namespace, target: tuple[str, int], info=None, log=print):
    from theempire.web import WebGateway
    gateway = WebGateway(target, args.bind, args.web, info, log)
    try:
        gateway.listen()
    except OSError as exc:
        print(f"Impossibile aprire la porta web {args.web}: {exc}", file=sys.stderr)
        return None
    return gateway


def _play_online(session, args: argparse.Namespace) -> None:
    from theempire.ui import UI
    locale.setlocale(locale.LC_ALL, "")
    audio = _audio(args)
    try:
        curses.wrapper(lambda scr: UI(scr, session, audio).run())
    finally:
        audio.close()
        session.close()


def join(args: argparse.Namespace) -> int:
    import getpass

    from theempire.net import RemoteSession
    host, port = _address(args.join)
    try:
        session = RemoteSession(host, port, args.name or getpass.getuser(),
                                args.faction[0] if args.faction else None, args.password)
    except (OSError, ConnectionError) as exc:
        print(f"Impossibile entrare nella partita su {host}:{port}: {exc}", file=sys.stderr)
        if args.audio_web:
            time.sleep(8)  # leave the message on the browser's screen for a while
        return 1
    _play_online(session, args)
    return 0


def web_only(args: argparse.Namespace) -> int:
    """--join HOST --web: a web gateway in front of someone else's server."""
    host, port = _address(args.join)
    gateway = _web(args, (host, port))
    if gateway is None:
        return 1
    try:
        gateway.serve_forever()
    except KeyboardInterrupt:
        gateway.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        list_scenarios()
        return 0
    if args.autoplay:
        return autoplay(args)
    if args.serve is not None:
        if args.play and args.play not in [f.key for f in SCENARIOS[args.scenario or "ww3"].factions] \
                and not args.load:
            print(f"Fazione sconosciuta: {args.play}", file=sys.stderr)
            return 2
        if args.play and args.faction and args.play not in args.faction:
            args.faction.append(args.play)
        return serve(args)
    if args.join and args.web is not None:
        return web_only(args)
    if args.join:
        return join(args)
    locale.setlocale(locale.LC_ALL, "")
    if args.scenario and args.faction:
        valid = {f.key for f in SCENARIOS[args.scenario].factions}
        bad = [f for f in args.faction if f not in valid]
        if bad:
            print(f"Fazione sconosciuta per {args.scenario}: {', '.join(bad)} "
                  f"(valide: {', '.join(sorted(valid))})", file=sys.stderr)
            return 2

    audio = _audio(args)

    def run(scr) -> None:
        from theempire.net import LocalSession
        from theempire.ui import UI, setup_menu
        audio.music("menu")
        turn_time = args.turn_time
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
                turn_time = choice.get("turn_time", 0) or turn_time
        UI(scr, LocalSession(game, args.save, turn_time), audio).run()

    try:
        curses.wrapper(run)
    finally:
        audio.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
