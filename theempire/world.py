"""The world grid: terrain, countries, cities, neighbourhoods and distances.

Cells are indexed by a flat integer ``i = y * width + x``. The map wraps
east-west (a cylinder) and is clamped north-south.

The cells are squares with 8 neighbours, or, as an option, hexagons with 6:
the same rows and columns, with the odd rows pushed half a cell to the east
(the "odd-r" layout of hex maps), so the land, the countries and the cities
stay where they are.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ASSET = Path(__file__).resolve().parent / "assets" / "world.json"
HD_ASSET = ASSET.with_name("land_hd.bin")   # the fine land mask for the zoom


@dataclass(frozen=True)
class CitySite:
    name: str
    iso: str
    cell: int
    size: int
    capital: bool
    pop: int


# hexagons: the neighbours of a cell of an even row and of an odd row
HEX_STEPS = (
    ((1, 0), (-1, 0), (-1, -1), (0, -1), (-1, 1), (0, 1)),
    ((1, 0), (-1, 0), (0, -1), (1, -1), (0, 1), (1, 1)),
)


class World:
    def __init__(self, data: dict, hexgrid: bool = False):
        self.hexgrid = hexgrid
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
            if hexgrid:
                steps = HEX_STEPS[y & 1]
            else:
                steps = tuple((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
            self.neighbors.append(tuple(
                (y + dy) * w + (x + dx) % w for dx, dy in steps if 0 <= y + dy < h))
        if hexgrid:
            self._keep_diagonals()
        self.coastal = bytearray(
            1 if self.land[i] and any(not self.land[n] for n in self.neighbors[i]) else 0
            for i in range(self.size)
        )
        self.region = self._regions()

    def _keep_diagonals(self) -> None:
        """Squares touching only at a corner were neighbours on the square
        grid, not on hexagons: a narrow strait (Sicily, the Dardanelles...)
        or a thin isthmus would close. Where two sea cells meet only across
        a corner of two land cells, one of the two becomes sea (never a
        city); the same for land, if no sea passage closes for it."""
        w, sites = self.width, {s.cell for s in self.sites}

        def broken(sea: bool):
            for a in range(self.size - w):
                if self.land[a] == sea:
                    continue
                x, y = a % w, a // w
                for dx in (-1, 1):
                    b = self.idx(x + dx, y + 1)
                    if self.land[b] == sea or b in self.neighbors[a]:
                        continue
                    between = [c for c in self.neighbors[a] if c in self.neighbors[b]]
                    if all(self.land[c] == sea for c in between):
                        yield between

        for between in list(broken(True)):
            cell = next((c for c in between if c not in sites), None)
            if cell is not None and all(self.land[c] for c in between):
                self.land[cell] = 0
        for between in list(broken(False)):
            for cell in between:
                if not self.land[cell] and self._still_open_without(cell):
                    self.land[cell] = 1
                    break

    def _still_open_without(self, cell: int) -> bool:
        """Would the sea around ``cell`` stay connected if it were land?"""
        seas = [n for n in self.neighbors[cell] if not self.land[n]]
        if len(seas) < 2:
            return True
        near = self.bfs([seas[0]], lambda i: i != cell and not self.land[i], limit=8)
        return all(n in near for n in seas)

    # -- geometry ---------------------------------------------------------
    def xy(self, i: int) -> tuple[int, int]:
        return i % self.width, i // self.width

    def idx(self, x: int, y: int) -> int:
        return y * self.width + x % self.width

    def lonlat(self, i: int) -> tuple[float, float]:
        x, y = self.xy(i)
        return self.lon0 + (x + 0.5) * self.dlon, self.lat0 - (y + 0.5) * self.dlat

    def dist(self, a: int, b: int) -> int:
        """Steps from cell to cell (Chebyshev distance on squares, hex
        distance on hexagons), wrapping east-west."""
        ax, ay = a % self.width, a // self.width
        bx, by = b % self.width, b // self.width
        if self.hexgrid:
            dx = (bx - ax + self.width // 2) % self.width - self.width // 2
            return _hex_dist(dx, ay, by)
        dx = abs(ax - bx)
        return max(min(dx, self.width - dx), abs(ay - by))

    def offset(self, a: int, b: int) -> tuple[int, int]:
        """(dx, dy) from ``a`` to ``b``, the short way round east-west. On
        hexagons dx counts half cells, as the odd rows are pushed half a
        cell east: the direction on the screen."""
        dx = b % self.width - a % self.width
        if dx > self.width // 2:
            dx -= self.width
        elif dx < -(self.width // 2):
            dx += self.width
        dy = b // self.width - a // self.width
        if self.hexgrid:
            return 2 * dx + (b // self.width & 1) - (a // self.width & 1), dy
        return dx, dy

    def ring(self, center: int, radius: int) -> list[int]:
        """All cells within ``radius`` steps of ``center``."""
        cx, cy = center % self.width, center // self.width
        offsets = _hex_offsets(radius, cy & 1) if self.hexgrid else _offsets(radius)
        return [self.idx(cx + dx, cy + dy) for dx, dy in offsets if 0 <= cy + dy < self.height]

    def step_dir(self, i: int, dx: int, dy: int) -> int | None:
        """The cell one step away in a direction (dx, dy each -1, 0 or 1).
        On hexagons there is no straight north or south: (±1, ±1) are the
        four slanted sides, None for (0, ±1)."""
        x, y = self.xy(i)
        if not 0 <= y + dy < self.height:
            return None
        if self.hexgrid and dy:
            if not dx:
                return None
            # odd rows sit half a cell east: their north-east is x + 1
            return self.idx(x + (y & 1) + (dx - 1) // 2, y + dy)
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


class LandHD:
    """Land and sea sampled ``zoom`` times finer than the Braille dots of the
    normal map (built by tools/build_world.py from Natural Earth)."""

    def __init__(self, data: bytes):
        import struct
        import zlib
        if data[:4] != b"TEHD":
            raise ValueError("not a land mask")
        self.width, self.height, self.zoom = struct.unpack(">HHH", data[4:10])
        self.bits = zlib.decompress(data[10:])
        self.stride = (self.width + 7) // 8

    def land(self, x: int, y: int) -> bool:
        x %= self.width
        if not 0 <= y < self.height:
            return False
        return bool(self.bits[y * self.stride + (x >> 3)] & (0x80 >> (x & 7)))


@lru_cache(maxsize=1)
def load_hd() -> LandHD | None:
    try:
        return LandHD(HD_ASSET.read_bytes())
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=None)
def _offsets(radius: int) -> tuple[tuple[int, int], ...]:
    return tuple((dx, dy) for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1))


def _hex_dist(dx: int, ay: int, by: int) -> int:
    """Hex distance from (0, ay) to (dx, by), odd-r layout, through the
    axial coordinates q = x - (y - y % 2) / 2, r = y."""
    dq = dx - (by - (by & 1)) // 2 + (ay - (ay & 1)) // 2
    dr = by - ay
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


@lru_cache(maxsize=None)
def _hex_offsets(radius: int, parity: int) -> tuple[tuple[int, int], ...]:
    return tuple((dx, dy) for dy in range(-radius, radius + 1) for dx in range(-radius - 1, radius + 2)
                 if _hex_dist(dx, parity, parity + dy) <= radius)


@lru_cache(maxsize=2)
def _data() -> str:
    return ASSET.read_text(encoding="utf-8")


@lru_cache(maxsize=2)
def load_world(hexgrid: bool = False) -> World:
    return World(json.loads(_data()), hexgrid=bool(hexgrid))
