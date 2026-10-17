"""The tutorial: an instructor who walks a new player through the game.

Each step explains one thing and waits until the player has really done it
(moved a unit, taken a city, played a card...). Steps without a check are
just explanations: they advance when the player presses a key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from theempire import cards


@dataclass
class Step:
    title: str
    text: list[str]
    check: Callable | None = None       # check(tutorial) -> bool; None = read and continue
    enter: Callable | None = None       # called once when the step starts


def _moved(t) -> bool:
    g = t.ui.g
    return any(a["op"] in ("move", "attack") and a["actor"] == t.ui.viewer and a["seq"] > t.mark
               for a in g.reel)


def _more_cities(t) -> bool:
    return len(t.ui.g.cities_of(t.ui.viewer)) > t.cities_at_start


def _give_spy(t) -> None:
    hand = t.ui.g.factions[t.ui.viewer].cards
    if "spy" not in hand:
        if len(hand) >= cards.HAND_LIMIT:
            hand.pop(0)
        hand.append("spy")


STEPS = [
    Step("Benvenuto, comandante", [
        "Questa è la guerra a scala mondiale: la mappa è il mondo vero.",
        "Guidi il Comando Italiano (blu). In Albania si è insediata la",
        "Repubblica Ribelle (rosso). Tutto il verde è neutrale.",
        "A destra c'è il pannello: le tue città, le unità, le fazioni.",
        "In alto a destra l'Orologio dell'Apocalisse: se arriva a mezzanotte",
        "per la guerra nucleare, perdono tutti.",
    ]),
    Step("Guardarsi intorno", [
        "Muovi il cursore con le FRECCE (o con il mouse; trascina per",
        "spostare la mappa). Premi m per la panoramica del mondo intero,",
        "poi m di nuovo per tornare qui.",
    ], check=lambda t: t.seen_overview),
    Step("Prendere il comando di un'unità", [
        "Le unità in città sono fortificate o di sentinella e non chiedono",
        "ordini. Porta il cursore su Roma (★ blu) e premi INVIO: selezioni",
        "un'unità (Invio di nuovo passa alla successiva). Oppure cliccala.",
        "Nel pannello leggi punti vita (PV), mosse e carburante.",
    ], check=lambda t: t.ui.active is not None),
    Step("Muovere", [
        "Muovi l'unità con  q w e / a d / z x c  (le 8 direzioni) o con il",
        "tastierino numerico. Col mouse: clic su una casella accanto.",
        "La fanteria ha 1 mossa, i corazzati 2, gli aerei 8 (ma consumano",
        "carburante: riforniscili in città o su una portaerei).",
    ], check=_moved),
    Step("Ordini di marcia", [
        "Per andare lontano: seleziona un corazzato, premi g, porta il",
        "cursore su Ljubljana o Zagreb (a nord-est) e premi Invio. Vedi il",
        "percorso; l'unità proseguirà da sola nei turni successivi.",
        "Col mouse: clic sulla destinazione e secondo clic per partire.",
        "Altri ordini: s sentinella, f fortifica, A affida l'unità all'IA.",
    ], check=lambda t: t.goto_given or any(
        u.order == "goto" for u in t.ui.g.units_of(t.ui.viewer))),
    Step("La produzione", [
        "Ogni città costruisce una cosa alla volta. Porta il cursore su",
        "Napoli e premi p (o Invio su una città vuota): scegli cosa costruire.",
        "Le città grandi e le capitali producono di più. Le navi si fanno solo",
        "nei porti. C'è un limite di unità (Unità n/limite nel pannello).",
    ], check=lambda t: any(c.manual for c in t.ui.g.cities_of(t.ui.viewer))),
    Step("Le direttive", [
        "Con un impero grande non serve decidere città per città: premi P",
        "e scegli una direttiva (per esempio 2, offensiva terrestre).",
        "Tutte le città si riconvertono; quelle scelte a mano restano tali.",
    ], check=lambda t: t.ui.g.factions[t.ui.viewer].directive != ""),
    Step("Fine del turno", [
        "Quando hai dato gli ordini premi E (fine turno). Poi muove la",
        "Repubblica Ribelle e all'inizio del tuo turno vedrai il BOLLETTINO",
        "DI GUERRA: cosa hanno fatto gli altri, attacco per attacco.",
        "B rilegge i bollettini quando vuoi.",
    ], check=lambda t: t.ui.g.turn > t.turn_at_step),
    Step("La prima conquista", [
        "Le città neutrali hanno una milizia. Per prenderle porta FANTERIA o",
        "CORAZZATI accanto e muovili contro la città: nel pannello vedi la",
        "probabilità di vittoria prima di attaccare. Più unità attorno al",
        "bersaglio = più forza (+15% ciascuna). Aerei e navi possono solo",
        "indebolirla. Conquista una città qualunque (Ljubljana, Zagreb...).",
    ], check=_more_cities),
    Step("Disordini e carte", [
        "La città conquistata è in DISORDINI per 5 turni: produce la metà.",
        "Conquistando hai guadagnato anche una CARTA (e qui te ne regalo",
        "un'altra). Premi K, scegli Spionaggio e giocalo sulla Repubblica",
        "Ribelle: vedrai tutto il suo esercito e un rapporto segreto.",
    ], check=lambda t: cards.spied(t.ui.g, t.ui.viewer) is not None, enter=_give_spy),
    Step("Il mare e il cielo", [
        "Le navi entrano solo nei porti amici. Il Trasporto (T) porta 6",
        "unità di terra: muovi la fanteria sulla nave per imbarcarla e verso",
        "terra per sbarcare. Sottomarini invisibili, cacciatorpediniere che",
        "li scovano, incrociatori che bombardano la costa, portaerei.",
    ]),
    Step("L'Orologio dell'Apocalisse", [
        "Negli altri scenari hai testate nucleari (N) e armi chimiche (C).",
        "Ogni uso avvicina la mezzanotte, e il nemico può rispondere.",
        "Le tregue (O) fermano la guerra con una fazione per 15 turni.",
        "Qui sei senza testate: vinci con l'esercito.",
    ]),
    Step("Obiettivo finale: Tirana", [
        "Conquista Tirana, la capitale della Repubblica Ribelle (★ rossa,",
        "oltre l'Adriatico). Puoi marciare attraverso i Balcani o sbarcare",
        "dal mare con il trasporto. Quando Tirana cade, il tutorial è finito.",
        "Suggerimento: un Piano quinquennale o i Rinforzi aiutano.",
    ], check=lambda t: False),
]


class Tutorial:
    def __init__(self, ui):
        self.ui = ui
        self.index = -1
        self.seen_overview = False
        self.goto_given = False
        self.mark = 0
        self.cities_at_start = 0
        self.turn_at_step = 0
        self.visible = True

    @property
    def step(self) -> Step | None:
        return STEPS[self.index] if 0 <= self.index < len(STEPS) else None

    def start(self) -> None:
        self.next()

    def next(self) -> None:
        """Move to the next step and introduce it."""
        ui = self.ui
        self.index += 1
        step = self.step
        if step is None:
            return
        g = ui.g
        self.mark = g.reel_seq
        self.cities_at_start = len(g.cities_of(ui.viewer))
        self.turn_at_step = g.turn
        if step.enter:
            step.enter(self)
        title = f"TUTORIAL {self.index + 1}/{len(STEPS)} · {step.title}"
        footer = "premi un tasto" if step.check else "premi un tasto per continuare"
        ui.draw()
        ui.dialog(title, step.text, footer)
        if step.check is None:
            self.next()

    def update(self) -> None:
        """Called after every action: has the player done what was asked?"""
        ui = self.ui
        if ui.mode == "overview":
            self.seen_overview = True
        step = self.step
        if step is None or step.check is None or ui.g.over:
            return
        if step.check(self):
            ui.audio.sfx("capture")
            ui.draw()
            ui.dialog("✔ Ben fatto!", [f"Passo completato: {step.title}."], "premi un tasto")
            self.next()

    def box(self) -> tuple[str, list[str]] | None:
        """What the instructor's box on the map shows."""
        step = self.step
        if step is None or not self.visible:
            return None
        return f" TUTORIAL {self.index + 1}/{len(STEPS)} · {step.title} · h nasconde ", step.text
