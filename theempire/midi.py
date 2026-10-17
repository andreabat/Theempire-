"""Standard MIDI files played with the game's own synthesizer.

The player can drop .mid files in ~/.theempire/music (or the folder named by
THEEMPIRE_MUSIC): they show up in the music menu, rendered once into the
sound cache. Nothing of them is shipped with the game.
"""

from __future__ import annotations

import os
import re
import struct
from pathlib import Path

MAX_SECONDS = 240.0   # long files are cut: it is background music


def music_dir() -> Path:
    env = os.environ.get("THEEMPIRE_MUSIC")
    return Path(env) if env else Path.home() / ".theempire" / "music"


def slug(path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-") or "brano"


def title(path: Path) -> str:
    return path.stem.replace("_", " ").strip()


def user_tracks(folder: Path | None = None) -> dict[str, Path]:
    """Music id ("user-<slug>") -> MIDI file, sorted by title."""
    folder = folder or music_dir()
    try:
        files = sorted(p for p in folder.iterdir()
                       if p.suffix.lower() in (".mid", ".midi") and p.is_file())
    except OSError:
        return {}
    return {f"user-{slug(p)}": p for p in files}


# ------------------------------------------------------------------ parsing
def _vlq(data: bytes, i: int) -> tuple[int, int]:
    value = 0
    while True:
        b = data[i]
        i += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, i


def read(path: Path) -> list[tuple[float, float, int, int, int, int]]:
    """Notes as (start s, length s, pitch, velocity, channel, program)."""
    data = path.read_bytes()
    if data[:4] != b"MThd":
        raise ValueError("non è un file MIDI")
    _, ntracks, division = struct.unpack(">HHH", data[8:14])
    if division & 0x8000:
        raise ValueError("timecode SMPTE non supportato")
    i = 8 + struct.unpack(">I", data[4:8])[0]
    events = []        # (tick, order, kind, channel, a, b)
    tempos = []        # (tick, microseconds per quarter)
    while i + 8 <= len(data):
        tag, length = data[i:i + 4], struct.unpack(">I", data[i + 4:i + 8])[0]
        body = data[i + 8:i + 8 + length]
        i += 8 + length
        if tag != b"MTrk":
            continue
        tick, j, status = 0, 0, 0
        while j < len(body):
            delta, j = _vlq(body, j)
            tick += delta
            b = body[j]
            if b == 0xFF:
                kind = body[j + 1]
                n, k = _vlq(body, j + 2)
                if kind == 0x51 and n == 3:
                    tempos.append((tick, int.from_bytes(body[k:k + 3], "big")))
                j = k + n
                continue
            if b in (0xF0, 0xF7):
                n, k = _vlq(body, j + 1)
                j = k + n
                continue
            if b & 0x80:
                status = b
                j += 1
            size = 1 if status >> 4 in (0xC, 0xD) else 2
            args = body[j:j + size] + b"\0"
            j += size
            events.append((tick, len(events), status >> 4, status & 15, args[0], args[1]))
    events.sort()
    tempos.sort()
    tempos = tempos or [(0, 500000)]

    def seconds(tick: int) -> float:
        t, last_tick, us = 0.0, 0, 500000
        for at, value in tempos:
            if at >= tick:
                break
            t += (at - last_tick) * us / division / 1e6
            last_tick, us = at, value
        return t + (tick - last_tick) * us / division / 1e6

    program = [0] * 16
    started: dict[tuple[int, int], tuple[int, int]] = {}
    notes = []
    for tick, _, kind, ch, a, b in events:
        if kind == 0xC:
            program[ch] = a
        elif kind == 0x9 and b > 0:
            started[(ch, a)] = (tick, b)
        elif kind in (0x8, 0x9) and (ch, a) in started:
            t0, vel = started.pop((ch, a))
            s0 = seconds(t0)
            notes.append((s0, max(0.03, seconds(tick) - s0), a, vel, ch, program[ch]))
    return sorted(notes)


# ---------------------------------------------------------------- rendering
def render(path: Path):
    """The file mixed into an audio Track."""
    from theempire import audio

    notes = [n for n in read(path) if n[0] < MAX_SECONDS]
    if not notes:
        raise ValueError("nessuna nota")
    end = min(MAX_SECONDS, max(s + d for s, d, *_ in notes)) + 0.5
    track = audio.Track(end)
    for start, length, pitch, vel, ch, prog in notes:
        v = vel / 127
        if ch == 9:
            track.add(start, _drum(audio, pitch, v))
            continue
        f = 440.0 * 2 ** ((pitch - 69) / 12)
        length = min(length, end - start, 4.0)
        if 32 <= prog <= 39:                         # bass
            sound = audio.triangle(f, length, vol=0.35 * v, release=0.03)
        elif 24 <= prog <= 31 or prog <= 7:          # guitar, piano: plucked
            sound = audio.square(f, length, vol=0.07 * v, duty=0.25, decay=0.25,
                                 sustain=0.3, release=0.05)
        elif 52 <= prog <= 79:                       # voices, brass, reeds, pipes: the tune
            sound = audio.square(f, length, vol=0.16 * v, duty=0.25, release=0.04)
        else:
            sound = audio.triangle(f, length, vol=0.2 * v, release=0.05)
        track.add(start, sound)
    return track


def _drum(audio, pitch: int, v: float) -> list[float]:
    if pitch in (35, 36):
        return audio.sine_sweep(120, 40, 0.15, vol=0.7 * v, release=0.08)
    if pitch in (38, 40, 37, 39):
        return audio.noise(0.12, vol=0.3 * v, cutoff=0.6, decay=0.03, sustain=0.0)
    if pitch in (49, 51, 52, 55, 57, 59):
        return audio.noise(0.4, vol=0.12 * v, cutoff=0.9, decay=0.15, sustain=0.0)
    return audio.noise(0.05, vol=0.12 * v, cutoff=0.95, decay=0.02, sustain=0.0, seed=pitch)
