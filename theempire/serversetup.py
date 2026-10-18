"""The setup screen of an online game: every option of ``--serve`` on one
page, so that nobody has to remember the command line.

The form only builds a configuration (a plain dict); cli.py turns it into
the same arguments the command line would give, and shows the equivalent
command so it can be reused in scripts.
"""

from __future__ import annotations

import curses
import getpass
import shlex
import socket
from dataclasses import dataclass, field
from pathlib import Path

from theempire import i18n
from theempire.game import DIFFICULTY
from theempire.i18n import tr, word
from theempire.net import DEFAULT_PORT
from theempire.scenarios import SCENARIOS

TURN_TIMES = (0, 60, 90, 120, 180, 300)
PULSES = (0, 5, 10, 20)        # real time: seconds between pulses (0 = turns)
SAVES = Path.home() / ".theempire"


@dataclass
class Config:
    load: Path | None = None
    scenario: str = "ww3"
    humans: dict[str, bool] = field(default_factory=dict)   # faction key -> seat for a player
    play: str = ""                                          # "" = server only
    name: str = ""
    difficulty: str = "normale"
    turn_time: int = 0
    realtime: int = 0
    objectives: bool = True
    world_events: bool = True
    port: int = DEFAULT_PORT
    web: bool = True
    web_port: int = 8080
    password: str = ""

    def __post_init__(self) -> None:
        self.reset_seats()

    def reset_seats(self) -> None:
        keys = [f.key for f in SCENARIOS[self.scenario].factions]
        if set(self.humans) != set(keys):
            self.humans = {k: True for k in keys}
        if self.play not in keys:
            self.play = ""

    def seats(self) -> list[str]:
        return [k for k, human in self.humans.items() if human]

    def problem(self) -> str | None:
        """Why the server cannot start like this (None: it can)."""
        if self.load is None and not self.seats():
            return tr("Serve almeno un posto per un giocatore umano.")
        if self.web and self.web_port == self.port:
            return tr("La porta web deve essere diversa da quella di gioco.")
        if not (1 <= self.port <= 65535 and 1 <= self.web_port <= 65535):
            return tr("Le porte vanno da 1 a 65535.")
        return None

    def argv(self) -> list[str]:
        """The equivalent command line."""
        out = ["--serve", str(self.port)]
        if self.load is not None:
            out += ["--load", str(self.load)]
        else:
            out += ["--scenario", self.scenario]
            for key in self.seats():
                out += ["--faction", key]
            if self.difficulty != "normale":
                out += ["--difficulty", self.difficulty]
            if not self.objectives:
                out.append("--senza-obiettivi")
            if not self.world_events:
                out.append("--senza-eventi")
            if self.realtime:
                out += ["--realtime", str(self.realtime)]
        if self.turn_time and not self.realtime:
            out += ["--turn-time", str(self.turn_time)]
        if self.web:
            out += ["--web", str(self.web_port)]
        if self.play:
            out += ["--play", self.play]
            if self.name:
                out += ["--name", self.name]
        if i18n.language() != i18n.DEFAULT:
            out += ["--lang", i18n.language()]
        return out

    def command(self) -> str:
        line = "python3 -m theempire " + " ".join(shlex.quote(a) for a in self.argv())
        if self.password:
            line += "  " + tr("--password ... (o la variabile THEEMPIRE_PASSWORD)")
        return line


def saved_games() -> list[Path]:
    try:
        return sorted(SAVES.glob("server-*.json"), key=lambda p: -p.stat().st_mtime)
    except OSError:
        return []


def lan_address() -> str:
    """This machine's address on the local network (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return socket.gethostname()


# --------------------------------------------------------------------- form
@dataclass
class Row:
    label: str
    value: str
    help: str
    change: object = None      # change(step) for ←/→, or None
    text: object = None        # (getter, setter, max length, digits only) for typed fields
    action: str = ""           # "start" / "cancel"


def _rows(c: Config) -> list[Row]:
    sc = SCENARIOS[c.scenario]
    names = {f.key: f.name for f in sc.factions}
    saves = saved_games()
    rows: list[Row] = []
    yes, no = tr("sì"), tr("no")

    def cycle(options, current, step):
        k = options.index(current) if current in options else 0
        return options[(k + step) % len(options)]

    def set_lang(step):
        # immediate: the form is redrawn in the new language
        i18n.set_language(cycle(list(i18n.LANGS), i18n.language(), step))
        i18n.save_language(i18n.language())
    rows.append(Row(tr("Lingua"), i18n.LANGS[i18n.language()],
                    tr("La lingua del gioco (chi entra dal browser sceglie la sua)."), set_lang))

    def set_load(step):
        options = [None] + saves
        c.load = cycle(options, c.load, step)
    rows.append(Row(tr("Partita"),
                    tr("nuova") if c.load is None else tr("riprendi {file}", file=c.load.name),
                    tr("Una partita nuova, o una salvata da un server precedente (si salva da sola)."),
                    set_load if saves else None))
    if c.load is None:
        keys = [k for k in SCENARIOS if k != "tutorial"]

        def set_scenario(step):
            c.scenario = cycle(keys, c.scenario, step)
            c.reset_seats()
        rows.append(Row(tr("Scenario"), word(sc.name), word(sc.description), set_scenario))
        for f in sc.factions:
            def toggle(step, key=f.key):
                c.humans[key] = not c.humans[key]
                if not c.humans[key] and c.play == key:
                    c.play = ""
            rows.append(Row(f"  {word(f.name)}", tr("giocatore umano") if c.humans[f.key] else tr("IA"),
                            tr("Un posto per un giocatore (dal terminale o dal browser), "
                               "o guidata dall'IA."),
                            toggle))

        def set_difficulty(step):
            c.difficulty = cycle(list(DIFFICULTY), c.difficulty, step)
        rows.append(Row(tr("Difficoltà dell'IA"), word(c.difficulty),
                        tr("facile: IA con industria al 75% · normale · difficile: al 130%."),
                        set_difficulty))

        def set_objectives(step):
            c.objectives = not c.objectives
        rows.append(Row(tr("Obiettivi segreti"), yes if c.objectives else no,
                        tr("Ogni fazione riceve un obiettivo segreto: chi lo completa vince subito."),
                        set_objectives))

        def set_events(step):
            c.world_events = not c.world_events
        rows.append(Row(tr("Eventi mondiali"), yes if c.world_events else no,
                        tr("Ogni 5-8 turni un evento per tutti: crisi petrolifera, carestia, ONU..."),
                        set_events))

    if c.load is None:
        def set_mode(step):
            c.realtime = cycle(list(PULSES), c.realtime, step)
        rows.append(Row(tr("Modalità"),
                        tr("tempo reale, un impulso ogni {seconds} s", seconds=c.realtime)
                        if c.realtime else tr("a turni"),
                        tr("Tempo reale: tutti giocano insieme, senza turni; a ogni impulso le mosse "
                           "si ricaricano, le città producono e l'IA agisce."), set_mode))

    def set_time(step):
        c.turn_time = cycle(list(TURN_TIMES), c.turn_time, step)
    if not c.realtime or c.load is not None:
        rows.append(Row(tr("Tempo per turno"),
                        tr("{seconds} secondi", seconds=c.turn_time) if c.turn_time else tr("nessun limite"),
                        tr("Allo scadere il turno del giocatore finisce da solo: dà ritmo alla partita."),
                        set_time))
    seats = [""] + (c.seats() if c.load is None else [])

    def set_play(step):
        c.play = cycle(seats, c.play, step)
    rows.append(Row(tr("Tu giochi con"), word(names[c.play]) if c.play in names else
                    tr("nessuna: solo server"),
                    tr("Gioca anche tu da questo terminale, o lascia il server solo ad aspettare."),
                    set_play if len(seats) > 1 else None))
    if c.play:
        rows.append(Row(tr("Il tuo nome"), c.name or getpass.getuser(), tr("Come ti vedono gli altri."),
                        text=(lambda: c.name, lambda v: setattr(c, "name", v), 24, False)))
    rows.append(Row(tr("Porta di gioco"), str(c.port),
                    tr("I client entrano con: --join INDIRIZZO:PORTA."),
                    text=(lambda: str(c.port), lambda v: setattr(c, "port", int(v or 0)), 5, True)))

    def set_web(step):
        c.web = not c.web
    rows.append(Row(tr("Web TUI (browser)"), yes if c.web else no,
                    tr("Si gioca anche dal browser, senza installare nulla."), set_web))
    if c.web:
        rows.append(Row(tr("Porta web"), str(c.web_port),
                        tr("L'indirizzo da aprire: http://INDIRIZZO:PORTA"),
                        text=(lambda: str(c.web_port), lambda v: setattr(c, "web_port", int(v or 0)),
                              5, True)))
    rows.append(Row(tr("Password"), "•" * len(c.password) or tr("nessuna"),
                    tr("Chi entra deve conoscerla (vuota: partita aperta a tutti)."),
                    text=(lambda: c.password, lambda v: setattr(c, "password", v), 32, False)))
    rows.append(Row(tr("▶ Avvia il server"), "", tr("Invio per partire."), action="start"))
    rows.append(Row(tr("Annulla"), "", tr("Torna indietro senza avviare nulla."), action="cancel"))
    return rows


def server_setup(scr, config: Config | None = None) -> Config | None:
    """The setup screen. Returns the configuration, or None if cancelled."""
    c = config or Config()
    curses.curs_set(0)
    scr.keypad(True)
    sel, message = 0, ""
    while True:
        rows = _rows(c)
        sel = max(0, min(sel, len(rows) - 1))
        scr.erase()
        h, w = scr.getmaxyx()
        _put(scr, 1, 2, tr("THE EMPIRE · ospita una partita online"), curses.A_BOLD)
        _put(scr, 2, 2, tr("↑↓ scegli · ←→ o spazio cambia · scrivi nei campi di testo · "
                           "Invio avvia · Esc annulla"), curses.A_DIM)
        y = 4
        for k, row in enumerate(rows):
            if row.action:
                y += 1 if row.action == "start" else 0
                _put(scr, y, 4, f" {row.label} ", curses.A_REVERSE | curses.A_BOLD if k == sel else curses.A_BOLD)
            else:
                arrows = "◀ " + row.value + " ▶" if row.change else row.value
                _put(scr, y, 4, f"{row.label:24s}", curses.A_BOLD if k == sel else 0)
                _put(scr, y, 30, f" {arrows} ", curses.A_REVERSE if k == sel else curses.A_DIM)
            y += 1
        y += 1
        _put(scr, y, 4, rows[sel].help, 0)
        problem = c.problem()
        _put(scr, y + 2, 4, message or (f"⚠ {problem}" if problem else ""), curses.A_BOLD)
        _put(scr, h - 3, 2, tr("Comando equivalente:"), curses.A_DIM)
        _put(scr, h - 2, 2, c.command(), curses.A_DIM)
        scr.refresh()
        key = scr.getch()
        message = ""
        row = rows[sel]
        if key == curses.KEY_UP:
            sel = (sel - 1) % len(rows)
        elif key in (curses.KEY_DOWN, 9):
            sel = (sel + 1) % len(rows)
        elif key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord(" ")) and row.change:
            row.change(-1 if key == curses.KEY_LEFT else 1)
        elif key == 27:
            return None
        elif key in (10, 13, curses.KEY_ENTER):
            if row.action == "cancel":
                return None
            if row.action == "start" or not row.text:
                if problem:
                    message = f"⚠ {problem}"
                elif row.action == "start":
                    return c
                else:
                    sel += 1
            else:
                sel += 1
        elif row.text and key in (curses.KEY_BACKSPACE, 127, 8):
            get, set_, _, _ = row.text
            set_(get()[:-1])
        elif row.text and 32 <= key < 127:
            get, set_, limit, digits = row.text
            ch = chr(key)
            if (ch.isdigit() or not digits) and len(get()) < limit:
                set_(get() + ch)


def _put(scr, y: int, x: int, text: str, attr: int = 0) -> None:
    h, w = scr.getmaxyx()
    if 0 <= y < h and x < w - 1:
        try:
            scr.addstr(y, x, text[: w - 1 - x], attr)
        except curses.error:
            pass
