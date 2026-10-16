"""The world grid: terrain, countries, cities, neighbourhoods and distances.

Cells are indexed by a flat integer ``i = y * width + x``. The map wraps
east-west (a cylinder, like Empire) and is clamped north-south.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ASSET = Path(__file__).resolve().parent / "assets" / "world.json"


@dataclass(frozen=True)
class CitySite:
    name: str
    iso: str
    cell: int
    size: int
    capital: bool
    pop: int


class World:
    def __init__(self, data: dict):
        self.width: int = data["width"]
        self.height: int = data["height"]
        self.lon0: float = data["lon0"]
        self.lat0: float = data["lat0"]
        self.dlon: float = data["dlon"]
        self.dlat: float = data["dlat"]
        w, h = self.width, self.height
        self.size = w * h
        self.land = bytearray(1 if ch == "#" else 0 for row in data["land"] for ch in row)
        self.dots = [int(row[k:k + 2], 16) for row in data["dots"] for k in range(0, len(row), 2)]
        self.countries: list[dict] = data["countries"]
        self.country = [v for row in data["country_grid"] for v in row]  # 0 = none
        self.sites = [
            CitySite(c["name"], c["iso"], c["y"] * w + c["x"], c["size"], c["capital"], c["pop"])
            for c in data["cities"]
        ]
        for site in self.sites:
            self.land[site.cell] = 1
        self.neighbors: list[tuple[int, ...]] = []
        for i in range(self.size):
            x, y = i % w, i // w
            out = []
            for dy in (-1, 0, 1):
                ny = y + dy
                if not 0 <= ny < h:
                    continue
                for dx in (-1, 0, 1):
                    if dx or dy:
                        out.append(ny * w + (x + dx) % w)
            self.neighbors.append(tuple(out))
        self.coastal = bytearray(
            1 if self.land[i] and any(not self.land[n] for n in self.neighbors[i]) else 0
            for i in range(self.size)
        )
        self.region = self._regions()

    # -- geometry ---------------------------------------------------------
    def xy(self, i: int) -> tuple[int, int]:
        return i % self.width, i // self.width

    def idx(self, x: int, y: int) -> int:
        return y * self.width + x % self.width

    def lonlat(self, i: int) -> tuple[float, float]:
        x, y = self.xy(i)
        return self.lon0 + (x + 0.5) * self.dlon, self.lat0 - (y + 0.5) * self.dlat

    def dist(self, a: int, b: int) -> int:
        """Chebyshev distance in cells, wrapping east-west."""
        ax, ay = a % self.width, a // self.width
        bx, by = b % self.width, b // self.width
        dx = abs(ax - bx)
        return max(min(dx, self.width - dx), abs(ay - by))

    def ring(self, center: int, radius: int) -> list[int]:
        """All cells within ``radius`` (Chebyshev) of ``center``."""
        return [self.idx(center % self.width + dx, center // self.width + dy)
                for dx, dy in _offsets(radius)
                if 0 <= center // self.width + dy < self.height]

    def step_dir(self, i: int, dx: int, dy: int) -> int | None:
        x, y = self.xy(i)
        if not 0 <= y + dy < self.height:
            return None
        return self.idx(x + dx, y + dy)

    def country_of(self, i: int) -> dict | None:
        v = self.country[i]
        return self.countries[v - 1] if v else None

    def _regions(self) -> list[int]:
        """Connected land masses (ids >= 1) and water bodies (ids <= -1)."""
        region = [0] * self.size
        next_land, next_sea = 1, -1
        for start in range(self.size):
            if region[start]:
                continue
            is_land = self.land[start]
            rid = next_land if is_land else next_sea
            if is_land:
                next_land += 1
            else:
                next_sea -= 1
            region[start] = rid
            queue = deque([start])
            while queue:
                c = queue.popleft()
                for n in self.neighbors[c]:
                    if not region[n] and self.land[n] == is_land:
                        region[n] = rid
                        queue.append(n)
        return region

    def bfs(self, sources, passable, limit: int | None = None) -> dict[int, int]:
        """Multi-source breadth-first distances over cells where passable(i)."""
        dist = {s: 0 for s in sources}
        queue = deque(dist)
        while queue:
            c = queue.popleft()
            d = dist[c] + 1
            if limit is not None and d > limit:
                continue
            for n in self.neighbors[c]:
                if n not in dist and passable(n):
                    dist[n] = d
                    queue.append(n)
        return dist


@lru_cache(maxsize=None)
def _offsets(radius: int) -> tuple[tuple[int, int], ...]:
    return tuple((dx, dy) for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1))


@lru_cache(maxsize=1)
def load_world() -> World:
    return World(json.loads(ASSET.read_text(encoding="utf-8")))
