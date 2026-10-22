"""Command line entry point: ``python -m theempire`` or ``theempire``."""

from __future__ import annotations

import argparse
import curses
import locale
import os
import sys
import time
from pathlib import Path

from theempire import __version__, i18n
from theempire.ai import AI
from theempire.game import DIFFICULTY, Game
from theempire.i18n import tr, word
from theempire.net import DEFAULT_PORT
from theempire.scenarios import SCENARIOS


def _lang_arg(argv: list[str]) -> str | None:
    """--lang X or --lang=X, read before the parser exists so that its help
    texts are already in the right language."""
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.partition("=")[2]
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = sys.argv[1:] if argv is None else argv
    # set_language also exports THEEMPIRE_LANG: --join/--serve/web TUI children inherit it
    i18n.set_language(i18n.detect(_lang_arg(argv)))
    p = argparse.ArgumentParser(
        prog="theempire",
        description=tr("Gioco di strategia globale a turni nel terminale "
                       "(ispirato a Theatre Europe)."))
    p.add_argument("--lang", choices=list(i18n.LANGS), help=tr("lingua del gioco"))
    p.add_argument("--scenario", choices=sorted(SCENARIOS), help=tr("scenario (salta il menu)"))
    p.add_argument("--faction", action="append", default=[],
                   help=tr("fazione umana; ripeti per l'hot-seat (es. --faction west --faction east)"))
    p.add_argument("--difficulty", choices=list(DIFFICULTY), default="normale")
    p.add_argument("--seed", type=int, default=None, help=tr("seme casuale per partite ripetibili"))
    p.add_argument("--load", type=Path, nargs="?", const=Path.home() / ".theempire" / "save.json",
                   help=tr("carica una partita salvata"))
    p.add_argument("--save", type=Path, default=Path.home() / ".theempire" / "save.json",
                   help=tr("file di salvataggio"))
    turns = tr("TURNI")
    p.add_argument("--autoplay", type=int, metavar=turns,
                   help=tr("partita IA contro IA senza interfaccia, per {turns} turni", turns=turns))
    p.add_argument("--list", action="store_true", help=tr("elenca scenari e fazioni"))
    p.add_argument("--senza-obiettivi", dest="objectives", action="store_false", default=None,
                   help=tr("niente obiettivi segreti"))
    p.add_argument("--senza-eventi", dest="world_events", action="store_false", default=None,
                   help=tr("niente eventi mondiali"))
    p.add_argument("--audio", choices=["all", "sfx", "off"],
                   help=tr("musica ed effetti, solo effetti, o niente (predefinito: l'ultima "
                           "scelta; tasto M per il menu audio)"))
    p.add_argument("--muto", dest="audio", action="store_const", const="off",
                   help=tr("niente audio"))
    online = p.add_argument_group(tr("partita online"))
    port, faction = tr("PORTA"), tr("FAZIONE")
    online.add_argument("--serve", type=int, nargs="?", const=DEFAULT_PORT, metavar=port,
                        help=tr("ospita una partita online (porta predefinita {port}); "
                                "le fazioni date con --faction sono i posti per i giocatori, "
                                "le altre le guida l'IA. Senza --scenario né --load si apre "
                                "la schermata di configurazione", port=DEFAULT_PORT))
    online.add_argument("--bind", default="0.0.0.0", help=tr("indirizzo su cui ascoltare (server)"))
    online.add_argument("--play", metavar=faction,
                        help=tr("con --serve: gioca anche tu, da questo terminale, con {faction}",
                                faction=faction))
    online.add_argument("--join", metavar=tr("HOST[:PORTA]"), help=tr("entra in una partita online"))
    online.add_argument("--name", default="", help=tr("il tuo nome nella partita online"))
    online.add_argument("--password", default=os.environ.get("THEEMPIRE_PASSWORD", ""),
                        help=tr("password della partita online (anche da THEEMPIRE_PASSWORD)"))
    online.add_argument("--web", type=int, nargs="?", const=8080, metavar=port,
                        help=tr("con --serve o --join: apri anche la web TUI, per giocare dal "
                                "browser (porta predefinita {port})", port=8080))
    online.add_argument("--audio-web", action="store_true", help=argparse.SUPPRESS)
    online.add_argument("--turn-time", type=int, default=0, metavar=tr("SECONDI"),
                        help=tr("tempo massimo per turno di ogni giocatore (anche in locale)"))
    p.add_argument("--realtime", type=int, nargs="?", const=10, default=0, metavar=tr("SECONDI"),
                   help=tr("tempo reale, senza turni: un impulso ogni SECONDI (predefinito 10); "
                           "anche online"))
    p.add_argument("--esagoni", dest="hexgrid", action="store_true",
                   help=tr("griglia a esagoni (6 direzioni) invece che a quadrati (8)"))
    p.add_argument("--version", action="version", version=f"theempire {__version__}")
    return p.parse_args(argv)


def list_scenarios() -> None:
    for s in SCENARIOS.values():
        print(f"{s.key:8s} {word(s.name)}")
        print(f"         {word(s.description)}")
        for f in s.factions:
            print(f"           --faction {f.key:6s} {word(f.name)}")


def autoplay(args: argparse.Namespace) -> int:
    g = Game(args.scenario or "ww3", difficulty=args.difficulty, seed=args.seed,
             objectives=args.objectives, world_events=args.world_events,
             realtime=args.realtime, hexgrid=args.hexgrid)
    t0 = time.time()
    while not g.over and g.turn <= args.autoplay:
        AI(g, g.current).play()
        g.end_turn()
        if g.current == 0 and (g.turn % 10 == 0 or g.over):
            parts = [f"{f.key} {len(g.cities_of(f.idx))}c/{len(g.units_of(f.idx))}u/{f.warheads}☢"
                     for f in g.factions]
            print(tr("turno {turn:3d}  orologio {clock:2d}'  {factions}  neutrali {neutral}c  "
                     "({secs:.0f}s)", turn=g.turn, clock=g.doomsday, factions="  ".join(parts),
                     neutral=len(g.cities_of(None)), secs=time.time() - t0), flush=True)
    for e in g.events[-12:]:
        print(f"[{e.turn}] {i18n.render(e.text)}")
    if g.over:
        winner, reason = g.over
        print(tr("FINE: {reason} {winner}", reason=reason,
                 winner=g.factions[winner].name if winner is not None else tr("nessuno")))
    return 0


def _address(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":") if ":" in text else (text, "", "")
    return (host or "127.0.0.1"), int(port) if port else DEFAULT_PORT


def configure_server(args: argparse.Namespace) -> bool:
    """The setup screen of --serve: fills ``args`` like the command line
    would. False if the player cancelled."""
    from theempire.serversetup import Config, server_setup
    config = Config(port=args.serve or DEFAULT_PORT, password=args.password, name=args.name,
                    turn_time=args.turn_time, difficulty=args.difficulty)
    if args.web is not None:
        config.web_port = args.web
    locale.setlocale(locale.LC_ALL, "")
    chosen = curses.wrapper(lambda scr: server_setup(scr, config))
    if chosen is None:
        return False
    args.serve, args.load = chosen.port, chosen.load
    args.scenario, args.faction = chosen.scenario, chosen.seats()
    args.play, args.name = chosen.play or None, chosen.name
    args.difficulty, args.turn_time = chosen.difficulty, chosen.turn_time
    args.realtime, args.hexgrid = chosen.realtime, chosen.hexgrid
    args.objectives, args.world_events = chosen.objectives, chosen.world_events
    args.web = chosen.web_port if chosen.web else None
    args.password = chosen.password
    print(tr("Comando equivalente, per la prossima volta:\n  {command}\n",
             command=chosen.command()))
    return True


def _welcome(args: argparse.Namespace, port: int) -> None:
    """How the others get in, printed when the server starts."""
    from theempire.serversetup import lan_address
    ip = lan_address()
    command = f"python3 -m theempire --join {ip}:{port}" + ("  --password ..." if args.password else "")
    print(tr("I giocatori entrano con:  {command}", command=command))
    if args.web is not None:
        print(tr("Oppure dal browser:       {url}", url=f"http://{ip}:{args.web}/"))
        print(tr("Terminale nel browser:    {url}", url=f"http://{ip}:{args.web}/tui"))
    print(tr("Ctrl+C ferma il server (la partita viene salvata).") + "\n", flush=True)


def serve(args: argparse.Namespace) -> int:
    import getpass
    import threading

    from theempire.net import GameServer, RemoteSession
    if args.scenario is None and args.load is None and sys.stdin.isatty() and sys.stdout.isatty():
        if not configure_server(args):
            return 0
    save = args.save if args.save != Path.home() / ".theempire" / "save.json" else \
        Path.home() / ".theempire" / f"server-{args.serve}.json"
    if args.load:
        game = Game.load_file(args.load)
    else:
        scenario = args.scenario or "ww3"
        humans = tuple(args.faction) or tuple(f.key for f in SCENARIOS[scenario].factions)
        game = Game(scenario, humans=humans, difficulty=args.difficulty, seed=args.seed,
                    objectives=args.objectives, world_events=args.world_events,
                    realtime=args.realtime, hexgrid=args.hexgrid)
    log_lines: list[str] = []

    def log(line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        if args.play:
            log_lines.append(f"{stamp} {line}")
        else:
            print(f"{stamp} {line}", flush=True)

    server = GameServer(game, args.bind, args.serve, args.password, save, args.turn_time, log,
                        resume=args.load is not None)
    try:
        server.listen()
    except OSError as exc:
        print(tr("Impossibile aprire la porta {port}: {error}", port=args.serve, error=str(exc)),
              file=sys.stderr)
        return 1
    if args.web is not None:
        gateway = _web(args, ("127.0.0.1", server.port), server.web_info, log)
        if gateway is None:
            return 1
        threading.Thread(target=gateway.serve_forever, daemon=True).start()
        server.web_port = gateway.port
    if not args.play:
        _welcome(args, server.port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.save()
            server.stop()
            print("\n" + tr("Server fermato, partita salvata in {path}", path=str(save)))
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
        print(tr("Impossibile aprire la porta web {port}: {error}", port=args.web, error=str(exc)),
              file=sys.stderr)
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
        print(tr("Impossibile entrare nella partita su {address}: {error}",
                 address=f"{host}:{port}", error=str(exc)), file=sys.stderr)
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
            print(tr("Fazione sconosciuta: {faction}", faction=args.play), file=sys.stderr)
            return 2
        if args.play and args.faction and args.play not in args.faction:
            args.faction.append(args.play)
        return serve(args)
    if args.join and args.web is not None:
        return web_only(args)
    if args.join:
        return join(args)
    locale.setlocale(locale.LC_ALL, "")
    if args.realtime and len(args.faction) > 1 and args.serve is None:
        print(tr("In tempo reale si gioca uno per terminale: per più giocatori usa --serve."),
              file=sys.stderr)
        return 2
    if args.scenario and args.faction:
        valid = {f.key for f in SCENARIOS[args.scenario].factions}
        bad = [f for f in args.faction if f not in valid]
        if bad:
            print(tr("Fazione sconosciuta per {scenario}: {bad} (valide: {valid})",
                     scenario=args.scenario, bad=", ".join(bad), valid=", ".join(sorted(valid))),
                  file=sys.stderr)
            return 2

    audio = _audio(args)
    wants_server: list[bool] = []

    def run(scr) -> None:
        from theempire.net import LocalSession
        from theempire.ui import UI, setup_menu
        audio.music("menu")
        turn_time = args.turn_time
        if args.load:
            game = Game.load_file(args.load)
        elif args.scenario:
            humans = tuple(args.faction) or (SCENARIOS[args.scenario].factions[0].key,)
            game = Game(args.scenario, humans=humans, difficulty=args.difficulty, seed=args.seed,
                        objectives=args.objectives, world_events=args.world_events,
                        realtime=args.realtime, hexgrid=args.hexgrid)
        else:
            choice = setup_menu(scr)
            if choice is None:
                return
            if choice.get("serve"):
                wants_server.append(True)
                return
            if "load" in choice:
                if not choice["load"].exists():
                    return
                game = Game.load_file(choice["load"])
            else:
                game = Game(choice["scenario"], humans=choice["humans"],
                            difficulty=choice["difficulty"], seed=args.seed,
                            realtime=choice.get("realtime", 0) or args.realtime,
                            hexgrid=choice.get("hex", False) or args.hexgrid)
                turn_time = choice.get("turn_time", 0) or turn_time
        UI(scr, LocalSession(game, args.save, turn_time), audio).run()

    try:
        curses.wrapper(run)
    finally:
        audio.close()
    if wants_server:            # "Ospita una partita online" in the menu
        args.serve = args.serve or DEFAULT_PORT
        return serve(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
