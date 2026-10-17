"""Regions of the world, as continents on a board game: whoever holds every
city of a region gets a production bonus in all of its cities.

Cities are placed by the country they belong to; the few countries not
listed fall back on their longitude and latitude.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from theempire.i18n import N, Msg

if TYPE_CHECKING:
    from theempire.game import Game


@dataclass(frozen=True)
class Region:
    key: str
    name: str
    short: str
    countries: frozenset[str]


def _r(key: str, name: str, short: str, isos: str) -> Region:
    return Region(key, name, short, frozenset(isos.split()))


REGIONS: dict[str, Region] = {r.key: r for r in (
    _r("nam", N("Nord America"), N("N. America"), "USA CAN MEX BMU GRL"),
    _r("cam", N("America Centrale e Caraibi"), N("Centroamerica"),
       "GTM BLZ HND SLV NIC CRI PAN CUB HTI DOM JAM BHS TTO PRI KNA VCT LCA GRD ATG BRB DMA"),
    _r("sam", N("Sud America"), N("S. America"), "BRA ARG CHL PER BOL COL VEN ECU PRY URY GUY SUR FLK"),
    _r("weu", N("Europa Occidentale"), N("Europa Occ."),
       "GBR IRL FRA ESP PRT DEU ITA CHE AUT BEL NLD LUX DNK NOR SWE FIN ISL MLT AND MCO SMR LIE"),
    _r("eeu", N("Europa Orientale e Balcani"), N("Europa Or."),
       "POL CZE SVK HUN ROU BGR GRC ALB MNE SRB KOS HRV BIH SVN MKD UKR BLR MDA EST LVA LTU CYP"),
    _r("rus", N("Russia, Caucaso e Asia Centrale"), N("Russia-Asia C."),
       "RUS KAZ UZB TKM KGZ TJK ARM AZE GEO"),
    _r("mde", N("Medio Oriente"), N("Medio Oriente"),
       "TUR SYR IRQ IRN SAU YEM OMN ARE QAT KWT BHR JOR LBN ISR PSE"),
    _r("naf", N("Nord Africa"), N("Nord Africa"), "EGY LBY TUN DZA MAR MRT SDN ESH"),
    _r("saf", N("Africa Subsahariana"), N("Africa Sub."),
       "NGA ETH COD TZA KEN UGA AGO MOZ GHA MDG CMR CIV NER BFA MLI MWI ZMB SEN TCD SOM ZWE "
       "GIN RWA BEN BDI TGO SLE LBR CAF ERI GMB GAB BWA NAM LSO SWZ GNB GNQ COG DJI SSD ZAF "
       "MUS COM CPV STP SYC"),
    _r("sas", N("Asia Meridionale"), N("Asia Merid."), "IND PAK BGD NPL BTN LKA MDV AFG"),
    _r("eas", N("Asia Orientale"), N("Asia Orient."), "CHN JPN KOR PRK TWN MNG"),
    _r("sea", N("Sud-Est Asiatico"), N("Sud-Est As."), "VNM THA KHM LAO MMR MYS SGP IDN PHL BRN TLS"),
    _r("oce", N("Oceania"), N("Oceania"),
       "AUS NZL PNG FJI SLB VUT WSM TON KIR MHL PLW TUV FSM NRU"),
)}

BONUS_MIN, BONUS_MAX = 0.10, 0.30    # production bonus, growing with the region's size


def _fallback(lon: float, lat: float) -> str:
    """A region for a country not in the lists, from where it is."""
    if lon < -30:
        if lat > 24:
            return "nam"
        return "cam" if lat > 7 and lon > -120 else ("sam" if lon > -95 else "oce")
    if lon < 60 and lat > 35:
        return "weu" if lon < 15 else ("eeu" if lon < 40 else "rus")
    if lon < 52 and lat < 35:
        if lon > 35 and lat > 12:
            return "mde"
        return "naf" if lat > 17 else "saf"
    if lat > 45:
        return "rus"
    if lon < 90:
        return "mde" if lon < 60 else "sas"
    if lat < -10 or lon > 150:
        return "oce"
    return "eas" if lat > 22 else "sea"


_cache: dict[int, list[str]] = {}


def city_regions(game: "Game") -> list[str]:
    """The region key of every city, by city id."""
    key = id(game.world)
    if key not in _cache or len(_cache[key]) != len(game.cities):
        out = []
        for c in game.cities:
            region = next((r.key for r in REGIONS.values() if c.iso in r.countries), None)
            if region is None:
                region = _fallback(*game.world.lonlat(c.cell))
            out.append(region)
        _cache[key] = out
    return _cache[key]


def cities_in(game: "Game", key: str) -> list:
    regions = city_regions(game)
    return [c for c in game.cities if regions[c.id] == key]


_bonus: dict[int, dict[str, float]] = {}


def bonus_of(game: "Game", key: str) -> float:
    """The production bonus of a region: bigger regions are worth more."""
    cached = _bonus.get(id(game.world))
    if cached is None:
        sizes = {k: len(cities_in(game, k)) for k in REGIONS}
        lo, hi = min(sizes.values()), max(sizes.values())
        cached = _bonus[id(game.world)] = {
            k: round(BONUS_MIN + (n - lo) / max(1, hi - lo) * (BONUS_MAX - BONUS_MIN), 2)
            for k, n in sizes.items()}
    return cached[key]


def holder(game: "Game", key: str) -> int | None:
    """The faction holding every city of the region, if any."""
    owners = {c.owner for c in cities_in(game, key)}
    if len(owners) == 1:
        (owner,) = owners
        return owner
    return None


def held_by(game: "Game", f: int) -> list[str]:
    return [k for k, owner in game.region_holders.items() if owner == f]


def production_bonus(game: "Game", f: int) -> float:
    return sum(bonus_of(game, k) for k in held_by(game, f))


def progress(game: "Game", f: int) -> list[tuple[str, int, int]]:
    """(region, cities of f, cities in all) for the regions where f is
    present, the most complete first."""
    out = []
    for key in REGIONS:
        cities = cities_in(game, key)
        mine = sum(1 for c in cities if c.owner == f)
        if mine:
            out.append((key, mine, len(cities)))
    return sorted(out, key=lambda r: (r[1] < r[2], -(r[1] / r[2]), -r[1]))


def update(game: "Game") -> None:
    """Recompute who holds which region and announce the changes."""
    first = not game.region_holders
    for key, region in REGIONS.items():
        new = holder(game, key)
        old = game.region_holders.get(key)
        game.region_holders[key] = new
        if first or new == old:
            continue
        pct = int(bonus_of(game, key) * 100)
        if new is not None:
            game.log(Msg("{faction} controlla tutta la regione {region}: "
                         "+{pct}% di produzione in tutte le sue città.",
                         faction=game.factions[new].name, region=region.name, pct=pct),
                     None, "alert", "capture", new)
        if old is not None:
            game.log(Msg("{faction} perde il controllo della regione {region} (-{pct}% di produzione).",
                         faction=game.factions[old].name, region=region.name, pct=pct),
                     None, "alert", "alert", old)
