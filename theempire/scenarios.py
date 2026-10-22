"""Scenarios: who starts with what."""

from __future__ import annotations

from dataclasses import dataclass, field

from theempire.i18n import N


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
    capital_city: str = ""          # "Sei imperi": start with this city only
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
    modern: bool = True             # drones, hypersonic missiles and space weapons
    # a theatre of war: (west, east, south, north) in degrees; nothing outside
    # it takes part (no cities, no movement). None = the whole world.
    bounds: tuple[float, float, float, float] | None = None
    # the seas of the theatre, if wider than its land: so that the fleets can
    # sail round the coasts (the Mediterranean south of the last city...)
    sea_bounds: tuple[float, float, float, float] | None = None
    # cities given to a faction whatever their country: (city, faction key)
    city_owners: tuple[tuple[str, str], ...] = ()
    # countries whose cities stay out of a theatre that touches them
    outside: tuple[str, ...] = ()
    max_turns: int = 300
    missions: bool = True           # secret objectives (missions.py)
    world_events: bool = True       # world events every few rounds (events.py)


NATO_EUROPE = ("GBR", "FRA", "DEU", "ITA", "ESP", "PRT", "NLD", "BEL", "LUX", "NOR", "DNK",
               "ISL", "GRL", "GRC", "TUR")
NATO_EAST = ("POL", "CZE", "SVK", "HUN", "ROU", "BGR", "HRV", "SVN", "ALB", "MNE", "MKD",
             "EST", "LVA", "LTU", "FIN", "SWE")

SCENARIOS: dict[str, Scenario] = {s.key: s for s in (
    Scenario(
        "tutorial", N("Tutorial: la campagna dei Balcani"),
        N("Impara a giocare passo per passo: l'Italia contro una piccola Repubblica "
          "Ribelle in Albania. Un istruttore ti guida dai primi movimenti alla conquista "
          "di Tirana."),
        (
            FactionDef("ita", N("Comando Italiano"), "blue", ("ITA", "SMR", "VAT"),
                       doctrine="restrained", warheads=0, chemicals=0, nuclear=False),
            FactionDef("alb", N("Repubblica Ribelle"), "red", ("ALB",),
                       doctrine="restrained", warheads=0, chemicals=0, nuclear=False,
                       industry=0.4),
        ),
        doomsday=10,
        victory_share=0.9,
        max_turns=80,
        missions=False,
        world_events=False,
        modern=False,
    ),
    Scenario(
        "ww3", N("Terza Guerra Mondiale"),
        N("Tre blocchi armati fino ai denti si contendono il pianeta. "
          "Il resto del mondo è neutrale: conquistarlo vuol dire più industria."),
        (
            FactionDef("west", N("Alleanza Atlantica"), "blue",
                       ("USA", "CAN") + NATO_EUROPE + NATO_EAST +
                       ("UKR", "JPN", "KOR", "TWN", "AUS", "NZL"),
                       doctrine="restrained", warheads=20, chemicals=0, abm=0.25,
                       extras={"C": 3, "S": 3, "R": 2}),
            FactionDef("east", N("Unione Eurasiatica"), "red",
                       ("RUS", "BLR", "KAZ", "KGZ", "TJK", "ARM", "IRN", "SYR", "CUB", "VEN"),
                       doctrine="aggressive", warheads=20, chemicals=6, abm=0.2,
                       industry=1.5, extras={"S": 6, "A": 10, "B": 4}),
            FactionDef("china", N("Blocco Orientale"), "yellow",
                       ("CHN", "PRK", "PAK", "MMR", "LAO", "KHM"),
                       doctrine="balanced", warheads=10, chemicals=3, abm=0.15,
                       industry=1.35, extras={"I": 12, "S": 4, "A": 4}),
        ),
        doomsday=10,
        victory_share=0.55,
    ),
    Scenario(
        "coldwar", N("Guerra Fredda 1985"),
        N("NATO contro Patto di Varsavia, come in Theatre Europe, ma il teatro "
          "è il mondo intero. La Cina resta neutrale... per ora."),
        (
            FactionDef("nato", N("NATO"), "blue",
                       ("USA", "CAN") + NATO_EUROPE + ("JPN", "KOR"),
                       doctrine="restrained", warheads=25, chemicals=2, abm=0.2,
                       extras={"C": 3, "S": 3}),
            FactionDef("pact", N("Patto di Varsavia"), "red",
                       ("RUS", "UKR", "BLR", "MDA", "EST", "LVA", "LTU", "GEO", "ARM", "AZE",
                        "KAZ", "UZB", "TKM", "KGZ", "TJK", "POL", "CZE", "SVK", "HUN", "ROU",
                        "BGR", "CUB", "MNG"),
                       doctrine="aggressive", warheads=25, chemicals=8, abm=0.2,
                       industry=1.3, extras={"A": 12, "S": 6, "B": 4}),
        ),
        doomsday=7,
        victory_share=0.55,
        modern=False,                   # 1985: no drones, no hypersonics, no space war
    ),
    Scenario(
        "europe", N("Teatro Europa 1985"),
        N("La Guerra Fredda diventa calda, ma solo in Europa, dal Portogallo a Mosca: "
          "fronte compatto e partite brevi, come in Theatre Europe. La Germania è "
          "divisa; Svezia, Austria, Svizzera e Jugoslavia restano neutrali."),
        (
            FactionDef("nato", N("NATO"), "blue", NATO_EUROPE,
                       doctrine="restrained", warheads=12, chemicals=2, abm=0.2,
                       extras={"A": 6, "F": 4, "B": 2}),
            FactionDef("pact", N("Patto di Varsavia"), "red",
                       ("RUS", "UKR", "BLR", "MDA", "EST", "LVA", "LTU", "POL", "CZE", "SVK",
                        "HUN", "ROU", "BGR"),
                       doctrine="aggressive", warheads=12, chemicals=6, abm=0.2,
                       industry=1.2, extras={"A": 14, "B": 3}),
        ),
        doomsday=7,
        victory_share=0.75,                 # most cities are already taken at the start
        max_turns=150,
        modern=False,
        bounds=(-11.0, 42.0, 37.0, 71.0),      # from Lisbon to Moscow, from Athens to the North Cape
        sea_bounds=(-25.0, 42.0, 30.0, 75.0),  # the Atlantic off Europe and all the Mediterranean
        city_owners=(("Berlin", "pact"),),     # the capital of the GDR
        outside=("TUN", "DZA", "MAR", "SYR", "CYP", "MLT"),  # Africa and the Levant stay out
    ),
    Scenario(
        "empire", N("Sei imperi"),
        N("Sei imperi partono da una sola capitale; tutto il resto è da "
          "conquistare. Le armi atomiche vanno prima costruite."),
        (
            FactionDef("amer", N("Impero Americano"), "blue", (), capital_city="Washington, D.C."),
            FactionDef("braz", N("Impero Brasiliano"), "green", (), capital_city="Brasilia"),
            FactionDef("euro", N("Impero Europeo"), "cyan", (), capital_city="Paris"),
            FactionDef("afri", N("Impero Africano"), "magenta", (), capital_city="Abuja"),
            FactionDef("indi", N("Impero Indiano"), "orange", (), capital_city="New Delhi"),
            FactionDef("asia", N("Impero Asiatico"), "yellow", (), capital_city="Beijing"),
        ),
        doomsday=12,
        victory_share=0.5,
        start_forces=False,
        max_turns=400,
    ),
)}
