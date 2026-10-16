"""Unit types. Values are tuned for 1 cell = 1 degree of longitude."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnitType:
    key: str
    name: str
    domain: str          # land | sea | air
    move: int
    hp: int
    attack: int
    defense: int
    cost: int            # production points
    vision: int = 1
    fuel: int = 0        # air only: cells it can fly before landing
    capacity: int = 0    # cargo slots
    carries: str = ""    # domain of the cargo
    stealth: bool = False
    capture: bool = False


UNIT_TYPES: dict[str, UnitType] = {u.key: u for u in (
    UnitType("I", "Fanteria", "land", 1, 2, 2, 3, 6, capture=True),
    UnitType("A", "Corazzati", "land", 2, 3, 4, 2, 10, capture=True),
    UnitType("F", "Caccia", "air", 8, 1, 3, 3, 12, vision=2, fuel=16),
    UnitType("B", "Bombardiere", "air", 6, 2, 6, 1, 18, vision=2, fuel=24),
    UnitType("D", "Cacciatorpediniere", "sea", 3, 3, 2, 2, 12, vision=2),
    UnitType("S", "Sottomarino", "sea", 2, 2, 4, 1, 14, stealth=True),
    UnitType("T", "Trasporto", "sea", 3, 1, 0, 1, 10, capacity=6, carries="land"),
    UnitType("R", "Incrociatore", "sea", 2, 6, 3, 3, 22, vision=2),
    UnitType("C", "Portaerei", "sea", 2, 6, 1, 2, 28, vision=2, capacity=6, carries="air"),
)}

# Things a city can build that are not units.
WARHEAD = "N"
WARHEAD_COST = 45
CHEMICAL = "G"
CHEMICAL_COST = 20

PRODUCTION_NAMES = {**{k: u.name for k, u in UNIT_TYPES.items()},
                    WARHEAD: "Testata nucleare", CHEMICAL: "Armi chimiche"}


def production_cost(key: str) -> int:
    if key == WARHEAD:
        return WARHEAD_COST
    if key == CHEMICAL:
        return CHEMICAL_COST
    return UNIT_TYPES[key].cost
