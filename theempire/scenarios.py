"""Scenarios: who starts with what."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FactionDef:
    key: str
    name: str
    color: str
    countries: tuple[str, ...]
    doctrine: str = "balanced"      # restrained | balanced | aggressive
    warheads: int = 0
    chemicals: int = 0
    abm: float = 0.15               # chance to shoot down an incoming warhead
    nuclear: bool = True            # may build warheads
    industry: float = 1.0           # production multiplier (war economy)
    capital_city: str = ""          # Empire scenario: start with this city only
    extras: dict = field(default_factory=dict)  # extra starting units (type -> n)


@dataclass(frozen=True)
class Scenario:
    key: str
    name: str
    description: str
    factions: tuple[FactionDef, ...]
    doomsday: int = 10              # minutes to midnight
    victory_share: float = 0.5      # share of all cities for a domination win
    start_forces: bool = True       # garrison every starting city
    max_turns: int = 300


NATO_EUROPE = ("GBR", "FRA", "DEU", "ITA", "ESP", "PRT", "NLD", "BEL", "LUX", "NOR", "DNK",
               "ISL", "GRL", "GRC", "TUR")
NATO_EAST = ("POL", "CZE", "SVK", "HUN", "ROU", "BGR", "HRV", "SVN", "ALB", "MNE", "MKD",
             "EST", "LVA", "LTU", "FIN", "SWE")

SCENARIOS: dict[str, Scenario] = {s.key: s for s in (
    Scenario(
        "ww3", "Terza Guerra Mondiale",
        "Tre blocchi armati fino ai denti si contendono il pianeta. "
        "Il resto del mondo è neutrale: conquistarlo vuol dire più industria.",
        (
            FactionDef("west", "Alleanza Atlantica", "blue",
                       ("USA", "CAN") + NATO_EUROPE + NATO_EAST +
                       ("UKR", "JPN", "KOR", "TWN", "AUS", "NZL"),
                       doctrine="restrained", warheads=20, chemicals=0, abm=0.25,
                       extras={"C": 3, "S": 3, "R": 2}),
            FactionDef("east", "Unione Eurasiatica", "red",
                       ("RUS", "BLR", "KAZ", "KGZ", "TJK", "ARM", "IRN", "SYR", "CUB", "VEN"),
                       doctrine="aggressive", warheads=20, chemicals=6, abm=0.2,
                       industry=1.5, extras={"S": 6, "A": 10, "B": 4}),
            FactionDef("china", "Blocco Orientale", "yellow",
                       ("CHN", "PRK", "PAK", "MMR", "LAO", "KHM"),
                       doctrine="balanced", warheads=10, chemicals=3, abm=0.15,
                       industry=1.35, extras={"I": 12, "S": 4, "A": 4}),
        ),
        doomsday=10,
    ),
    Scenario(
        "coldwar", "Guerra Fredda 1985",
        "NATO contro Patto di Varsavia, come in Theatre Europe, ma il teatro "
        "è il mondo intero. La Cina resta neutrale... per ora.",
        (
            FactionDef("nato", "NATO", "blue",
                       ("USA", "CAN") + NATO_EUROPE + ("JPN", "KOR"),
                       doctrine="restrained", warheads=25, chemicals=2, abm=0.2,
                       extras={"C": 3, "S": 3}),
            FactionDef("pact", "Patto di Varsavia", "red",
                       ("RUS", "UKR", "BLR", "MDA", "EST", "LVA", "LTU", "GEO", "ARM", "AZE",
                        "KAZ", "UZB", "TKM", "KGZ", "TJK", "POL", "CZE", "SVK", "HUN", "ROU",
                        "BGR", "CUB", "MNG"),
                       doctrine="aggressive", warheads=25, chemicals=8, abm=0.2,
                       industry=1.6, extras={"A": 12, "S": 6, "B": 4}),
        ),
        doomsday=7,
        victory_share=0.45,
    ),
    Scenario(
        "empire", "Empire!",
        "Sei imperi partono da una sola capitale; tutto il resto è da "
        "conquistare. Le armi atomiche vanno prima costruite.",
        (
            FactionDef("amer", "Impero Americano", "blue", (), capital_city="Washington, D.C."),
            FactionDef("braz", "Impero Brasiliano", "green", (), capital_city="Brasilia"),
            FactionDef("euro", "Impero Europeo", "cyan", (), capital_city="Paris"),
            FactionDef("afri", "Impero Africano", "magenta", (), capital_city="Abuja"),
            FactionDef("indi", "Impero Indiano", "orange", (), capital_city="New Delhi"),
            FactionDef("asia", "Impero Asiatico", "yellow", (), capital_city="Beijing"),
        ),
        doomsday=12,
        victory_share=0.5,
        start_forces=False,
        max_turns=400,
    ),
)}
