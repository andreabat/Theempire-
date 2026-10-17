"""Build theempire/assets/world.json from Natural Earth data.

The game itself needs only the Python standard library; this offline tool
(numpy + Pillow) rasterises the Natural Earth 1:50m country polygons onto the
game grid, the same way Terrascope rasterises them onto Braille cells: every
grid cell is one terminal character made of 2x4 Braille dots, and every dot is
one land/sea sample.

Usage:
    python tools/build_world.py [--source DIR]

Natural Earth is public domain (https://www.naturalearthdata.com/).
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

BASE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
COUNTRIES = "ne_50m_admin_0_countries.geojson"
PLACES = "ne_10m_populated_places_simple.geojson"

# Grid geometry. One cell = DLON x DLAT degrees, rendered as one character.
# Terminal cells are about twice as tall as wide, so 1 x 2 degrees keeps the
# equirectangular map in proportion.
LON0, LAT0 = -180.0, 84.0   # top-left corner
DLON, DLAT = 1.0, 2.0
WIDTH = 360
HEIGHT = 72                 # 84N .. 60S (Antarctica left out)
SUB_X, SUB_Y = 2, 4         # Braille dots per cell
LAND_THRESHOLD = 3          # land dots (of 8) that make a cell land
MAX_CITIES = 320

# Braille dot bit for sub-sample (sx, sy).
DOT_BITS = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]

OUT = Path(__file__).resolve().parents[1] / "theempire" / "assets" / "world.json"
# The zoomed map: land/sea samples ZOOM_MAX times finer than the Braille dots
# of the normal map, so that a zoomed cell shows real detail (as Terrascope
# does) instead of the same dots blown up.
HD_OUT = OUT.with_name("land_hd.bin")
ZOOM_MAX = 4


def fetch(source: Path, name: str) -> dict:
    path = source / name
    if not path.exists():
        source.mkdir(parents=True, exist_ok=True)
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(BASE_URL + name, path)
    return json.loads(path.read_text(encoding="utf-8"))


def iso_of(props: dict) -> str:
    for key in ("ISO_A3", "ISO_A3_EH", "ADM0_A3", "SOV_A3"):
        code = props.get(key)
        if code and code != "-99":
            return code
    return props["ADM0_A3"]


def rasterize(countries: dict) -> tuple[np.ndarray, list[dict]]:
    """Return (sample grid of country index + 1, country table)."""
    sw, sh = WIDTH * SUB_X, HEIGHT * SUB_Y
    img = Image.new("I", (sw, sh), 0)
    draw = ImageDraw.Draw(img)
    sx = sw / (WIDTH * DLON)
    sy = sh / (HEIGHT * DLAT)
    table: list[dict] = []
    # Small countries last so they are not painted over by big neighbours.
    feats = sorted(countries["features"], key=lambda f: -(f["properties"].get("POP_EST") or 0))
    for feat in feats:
        props = feat["properties"]
        iso = iso_of(props)
        if iso == "ATA":
            continue
        table.append({"iso": iso, "name": props["NAME"], "pop": int(props.get("POP_EST") or 0)})
        value = len(table)
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            for k, ring in enumerate(poly):
                pts = [((lon - LON0) * sx, (LAT0 - lat) * sy) for lon, lat in ring]
                if len(pts) >= 3:
                    draw.polygon(pts, fill=0 if k else value)
    return np.array(img, dtype=np.int32), table


def build_hd(countries: dict) -> None:
    """Write the fine land mask: a small header, then zlib-packed bits,
    one row after the other, most significant bit first."""
    import struct
    import zlib
    sw, sh = WIDTH * SUB_X * ZOOM_MAX, HEIGHT * SUB_Y * ZOOM_MAX
    img = Image.new("1", (sw, sh), 0)
    draw = ImageDraw.Draw(img)
    sx, sy = sw / (WIDTH * DLON), sh / (HEIGHT * DLAT)
    for feat in countries["features"]:
        if iso_of(feat["properties"]) == "ATA":
            continue
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            for k, ring in enumerate(poly):
                pts = [((lon - LON0) * sx, (LAT0 - lat) * sy) for lon, lat in ring]
                if len(pts) >= 3:
                    draw.polygon(pts, fill=0 if k else 1)
    bits = np.packbits(np.array(img, dtype=np.uint8), axis=1)
    HD_OUT.write_bytes(b"TEHD" + struct.pack(">HHH", sw, sh, ZOOM_MAX)
                       + zlib.compress(bits.tobytes(), 9))
    print(f"wrote {HD_OUT} ({HD_OUT.stat().st_size // 1024} KiB): {sw}x{sh} samples")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("/tmp/ne"))
    parser.add_argument("--hd-only", action="store_true", help="only the zoomed land mask")
    args = parser.parse_args()
    countries = fetch(args.source, COUNTRIES)
    build_hd(countries)
    if args.hd_only:
        return
    places = fetch(args.source, PLACES)

    samples, table = rasterize(countries)
    land = np.zeros((HEIGHT, WIDTH), dtype=bool)
    country = np.zeros((HEIGHT, WIDTH), dtype=np.int32)  # 0 = sea
    dots = np.zeros((HEIGHT, WIDTH), dtype=np.int32)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            block = samples[y * SUB_Y:(y + 1) * SUB_Y, x * SUB_X:(x + 1) * SUB_X]
            bits = 0
            for j in range(SUB_Y):
                for i in range(SUB_X):
                    if block[j, i]:
                        bits |= DOT_BITS[j][i]
            dots[y, x] = bits
            nz = block[block > 0]
            if len(nz) >= LAND_THRESHOLD:
                land[y, x] = True
                values, counts = np.unique(nz, return_counts=True)
                country[y, x] = int(values[np.argmax(counts)])

    # Cities: every capital, then a quota per country (vast countries get
    # more, populous ones are capped), then the biggest remaining places.
    iso_index = {c["iso"]: i + 1 for i, c in enumerate(table)}
    land_count: dict[str, int] = {}
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if country[y, x]:
                iso = table[country[y, x] - 1]["iso"]
                land_count[iso] = land_count.get(iso, 0) + 1
    cand = []
    for feat in places["features"]:
        p = feat["properties"]
        lon, lat = p["longitude"], p["latitude"]
        if not (LAT0 - HEIGHT * DLAT < lat < LAT0):
            continue
        x = int((lon - LON0) / DLON) % WIDTH
        y = int((LAT0 - lat) / DLAT)
        capital = bool(p.get("adm0cap"))
        pop = int(p.get("pop_max") or 0)
        iso = p.get("adm0_a3")
        if iso not in iso_index and country[y, x]:
            iso = table[country[y, x] - 1]["iso"]
        cand.append({"name": p["nameascii"] or p["name"], "iso": iso, "x": x, "y": y,
                     "lon": lon, "lat": lat, "capital": capital, "pop": pop})
    cand.sort(key=lambda c: (not c["capital"], -c["pop"]))
    taken: set[tuple[int, int]] = set()
    per_country: dict[str, int] = {}
    cities = []

    def crowded(x: int, y: int) -> bool:
        return any(((x + dx) % WIDTH, y + dy) in taken for dx in (-1, 0, 1) for dy in (-1, 0, 1))

    def place(c: dict) -> bool:
        x, y = c["x"], c["y"]
        if (x, y) in taken or (not c["capital"] and crowded(x, y)):
            return False
        if not land[y, x]:
            best = None
            for dy in (0, -1, 1):
                for dx in (0, -1, 1, ):
                    nx, ny = (x + dx) % WIDTH, y + dy
                    if 0 <= ny < HEIGHT and land[ny, nx] and (nx, ny) not in taken:
                        best = best or (nx, ny)
            if best is None:
                if not c["capital"]:
                    return False
                land[y, x] = True  # a small island nation
                country[y, x] = iso_index.get(c["iso"], 0)
            else:
                x, y = best
        taken.add((x, y))
        per_country[c["iso"]] = per_country.get(c["iso"], 0) + 1
        pop = c["pop"]
        cities.append({"name": c["name"], "iso": c["iso"], "x": int(x), "y": int(y),
                       "lon": round(c["lon"], 3), "lat": round(c["lat"], 3),
                       "capital": c["capital"], "pop": pop,
                       "size": 3 if pop >= 5_000_000 else 2 if pop >= 1_000_000 else 1})
        return True

    placed: set[int] = set()
    for k, c in enumerate(cand):
        if c["capital"] and place(c):
            placed.add(k)
    for iso, cells in land_count.items():
        need = min(12, cells // 110)
        for k, c in enumerate(cand):
            if per_country.get(iso, 0) >= need:
                break
            if c["iso"] == iso and k not in placed and c["pop"] >= 20_000 and place(c):
                placed.add(k)
    for k, c in enumerate(cand):
        if len(cities) >= MAX_CITIES:
            break
        cap = 4 + land_count.get(c["iso"], 0) // 25
        if k not in placed and per_country.get(c["iso"], 0) < cap and place(c):
            placed.add(k)

    used = {c["iso"] for c in cities} | {table[v - 1]["iso"] for v in np.unique(country) if v}
    out = {
        "source": "Natural Earth 1:50m (public domain), grid built by tools/build_world.py",
        "lon0": LON0, "lat0": LAT0, "dlon": DLON, "dlat": DLAT,
        "width": WIDTH, "height": HEIGHT,
        "countries": [c for c in table if c["iso"] in used],
        "land": ["".join("#" if land[y, x] else "." for x in range(WIDTH)) for y in range(HEIGHT)],
        "dots": ["".join(f"{dots[y, x]:02x}" for x in range(WIDTH)) for y in range(HEIGHT)],
        "cities": cities,
    }
    kept = [c["iso"] for c in out["countries"]]
    remap = {i + 1: (kept.index(c["iso"]) + 1 if c["iso"] in kept else 0) for i, c in enumerate(table)}
    out["country_grid"] = [[remap.get(int(country[y, x]), 0) for x in range(WIDTH)] for y in range(HEIGHT)]
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KiB): "
          f"{int(land.sum())} land cells, {len(cities)} cities, {len(kept)} countries")


if __name__ == "__main__":
    main()
