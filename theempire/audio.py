"""Sound effects and chiptune music, synthesised in pure Python.

Nothing is shipped as audio: the first time the game runs, every effect and
tune is generated with simple square, triangle and noise oscillators (the
sound of an 8-bit home computer, like Theatre Europe's) and written as WAV
files to ``~/.theempire/sounds``. They are played with whatever command-line
player the system has (afplay, paplay, pw-play, aplay or ffplay). Without one,
the game falls back to the terminal bell for the important events.
"""

from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
import sys
import threading
import wave
from array import array
from pathlib import Path

RATE = 22050
VERSION = "v4"  # bump whenever a sound changes, so caches are rebuilt
CACHE = Path.home() / ".theempire" / "sounds" / VERSION
SETTINGS = Path.home() / ".theempire" / "settings.json"
LOOPING = {"menu", "war", "tension", "kalinka", "anthem"}
# What the player can pick as background music: "auto" follows the moment
# (menu, war, tension, victory, defeat, midnight), "off" means no music at
# all, anything else is a specific tune played on a loop.
MUSIC_CHOICES = ("auto", "off", "kalinka", "anthem", "menu", "war", "tension",
                 "victory", "defeat", "midnight")
MUSIC_NAMES = {"auto": "automatica (a seconda del momento)",
               "off": "nessuna musica (restano gli effetti)",
               "kalinka": "Kalinka",
               "anthem": "inno sovietico",
               "menu": "Toccata di Bach (menu)",
               "war": "marcia di guerra",
               "tension": "tensione",
               "victory": "vittoria",
               "defeat": "sconfitta",
               "midnight": "mezzanotte"}
MUSIC_KEYS = {"a": "auto", "o": "off", "k": "kalinka", "s": "anthem",
              "m": "menu", "w": "war", "t": "tension", "v": "victory",
              "d": "defeat", "n": "midnight"}

NOTES = {"C": -9, "C#": -8, "Db": -8, "D": -7, "D#": -6, "Eb": -6, "E": -5, "F": -4,
         "F#": -3, "Gb": -3, "G": -2, "G#": -1, "Ab": -1, "A": 0, "A#": 1, "Bb": 1, "B": 2}


def freq(note: str) -> float:
    """'A4' -> 440.0; 'R' (rest) -> 0."""
    if note == "R":
        return 0.0
    name, octave = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((NOTES[name] + 12 * (octave - 4)) / 12)


# ---------------------------------------------------------------- synthesis
class Track:
    """A mono float buffer that voices are mixed into."""

    def __init__(self, seconds: float):
        self.buf = [0.0] * int(seconds * RATE)

    def add(self, start: float, samples) -> None:
        i0 = int(start * RATE)
        buf = self.buf
        end = min(len(buf), i0 + len(samples))
        for k in range(max(0, -i0), end - i0):
            buf[i0 + k] += samples[k]

    def pcm(self, gain: float = 1.0) -> bytes:
        """16-bit samples, normalised so the loudest one is at ``gain``."""
        peak = max(1e-9, max(abs(v) for v in self.buf))
        scale = 32000 * gain / peak
        out = array("h", (int(v * scale) for v in self.buf))
        if sys.byteorder == "big":
            out.byteswap()
        return out.tobytes()


def envelope(n: int, attack: float = 0.005, decay: float = 0.0, sustain: float = 1.0,
             release: float = 0.02) -> list[float]:
    a, r = max(1, int(attack * RATE)), max(1, int(release * RATE))
    out = []
    for i in range(n):
        if i < a:
            v = i / a
        elif decay > 0:
            v = sustain + (1 - sustain) * math.exp(-(i - a) / (decay * RATE))
        else:
            v = sustain
        if i > n - r:
            v *= max(0.0, (n - i) / r)
        out.append(v)
    return out


def square(f: float, seconds: float, vol: float = 0.3, duty: float = 0.5, **env) -> list[float]:
    n = int(seconds * RATE)
    if f <= 0:
        return [0.0] * n
    e = envelope(n, **env)
    step = f / RATE
    return [(vol if (i * step) % 1.0 < duty else -vol) * e[i] for i in range(n)]


def triangle(f: float, seconds: float, vol: float = 0.4, **env) -> list[float]:
    n = int(seconds * RATE)
    if f <= 0:
        return [0.0] * n
    e = envelope(n, **env)
    step = f / RATE
    return [vol * (4 * abs((i * step) % 1.0 - 0.5) - 1) * e[i] for i in range(n)]


def sine_sweep(f0: float, f1: float, seconds: float, vol: float = 0.4, **env) -> list[float]:
    n = int(seconds * RATE)
    e = envelope(n, **env)
    out, phase = [], 0.0
    for i in range(n):
        f = f0 + (f1 - f0) * i / max(1, n - 1)
        phase += 2 * math.pi * f / RATE
        out.append(vol * math.sin(phase) * e[i])
    return out


def noise(seconds: float, vol: float = 0.4, cutoff: float = 1.0, seed: int = 1, **env) -> list[float]:
    """White noise through a one-pole low-pass (cutoff 0..1)."""
    rng = random.Random(seed)
    n = int(seconds * RATE)
    e = envelope(n, **env)
    out, y = [], 0.0
    for i in range(n):
        y += cutoff * (rng.uniform(-1, 1) - y)
        out.append(vol * y * e[i])
    return out


def bell(f: float, seconds: float, vol: float = 0.3) -> list[float]:
    n = int(seconds * RATE)
    return [vol * math.exp(-3 * i / n) * (math.sin(2 * math.pi * f * i / RATE)
                                          + 0.4 * math.sin(2 * math.pi * 2.76 * f * i / RATE))
            for i in range(n)]


def beat_time(tempo: list[tuple[float, float]], beat: float) -> float:
    """Seconds from the start to ``beat`` under a tempo map of (beat, bpm)."""
    t = 0.0
    for k, (b0, bpm) in enumerate(tempo):
        b1 = tempo[k + 1][0] if k + 1 < len(tempo) else math.inf
        if beat <= b0:
            break
        t += (min(beat, b1) - b0) * 60.0 / bpm
    return t


def sequence(track: Track, notes: list[tuple[str, float]], bpm, voice,
             start: float = 0.0, **kw) -> float:
    """Play (note, beats) pairs one after another; returns the end time.
    ``bpm`` is a number or a tempo map of (beat, bpm) changes."""
    tempo = bpm if isinstance(bpm, list) else [(0, bpm)]
    b = 0.0
    for note, beats in notes:
        t0, t1 = beat_time(tempo, b), beat_time(tempo, b + beats)
        if note != "R":
            track.add(start + t0, voice(freq(note), (t1 - t0) * 0.95, **kw))
        b += beats
    return start + beat_time(tempo, b)


def drums(track: Track, bpm: float, bars: int, start: float = 0.0, pattern: str = "k.s.k.s.") -> None:
    step = 60.0 / bpm / 2
    for b in range(bars):
        for k, hit in enumerate(pattern):
            t = start + (b * len(pattern) + k) * step
            if hit == "k":
                track.add(t, sine_sweep(120, 40, 0.15, vol=0.7, release=0.08))
            elif hit == "s":
                track.add(t, noise(0.12, vol=0.25, cutoff=0.6, seed=b * 9 + k, decay=0.03, sustain=0.0))


# -------------------------------------------------------------- the sounds
def tremolo(samples: list[float], rate: float, depth: float = 0.6) -> list[float]:
    return [v * (1 - depth / 2 + depth / 2 * math.sin(2 * math.pi * rate * i / RATE))
            for i, v in enumerate(samples)]


def _unit_sounds() -> dict[str, Track]:
    """Every unit type has its own voice, as in Empire: one sound when it
    moves and one when it opens fire."""
    out: dict[str, Track] = {}
    # Infantry: boots on the march / a volley of rifles.
    t = Track(0.45)
    for k in range(2):
        t.add(k * 0.2, noise(0.09, vol=0.5, cutoff=0.25, seed=21 + k, decay=0.02, sustain=0.0))
        t.add(k * 0.2, sine_sweep(110, 70, 0.07, vol=0.4, release=0.03))
    out["move_I"] = t
    t = Track(0.6)
    for k, at in enumerate((0.0, 0.09, 0.15, 0.3)):
        t.add(at, noise(0.08, vol=0.55, cutoff=0.9, seed=31 + k, attack=0.001, decay=0.015, sustain=0.0))
    out["fire_I"] = t
    # Armour: diesel rumble and clanking tracks / the main gun.
    t = Track(0.7)
    t.add(0, tremolo(square(55, 0.7, vol=0.25, duty=0.3, attack=0.05, release=0.15), 14))
    for k in range(5):
        t.add(0.05 + k * 0.12, noise(0.03, vol=0.25, cutoff=0.95, seed=41 + k, sustain=0.0, decay=0.008))
    out["move_A"] = t
    t = Track(0.9)
    t.add(0, sine_sweep(140, 35, 0.6, vol=1.0, attack=0.001, decay=0.15, sustain=0.0))
    t.add(0, noise(0.7, vol=0.7, cutoff=0.3, seed=51, attack=0.001, decay=0.12, sustain=0.0))
    out["fire_A"] = t
    # Fighter: a jet streaking past / cannon bursts.
    t = Track(0.8)
    t.add(0, noise(0.8, vol=0.45, cutoff=0.5, seed=61, attack=0.25, release=0.45))
    t.add(0, sine_sweep(900, 500, 0.8, vol=0.12, attack=0.25, release=0.45))
    out["move_F"] = t
    t = Track(0.6)
    for k in range(8):
        t.add(k * 0.06, noise(0.035, vol=0.5, cutoff=0.8, seed=71 + k, sustain=0.0, decay=0.01))
    out["fire_F"] = t
    # Bomber: heavy droning engines / falling bombs and explosions.
    t = Track(1.0)
    t.add(0, tremolo(square(82, 1.0, vol=0.18, duty=0.4, attack=0.2, release=0.3), 7, 0.8))
    t.add(0, tremolo(square(87, 1.0, vol=0.12, duty=0.4, attack=0.2, release=0.3), 6, 0.8))
    out["move_B"] = t
    t = Track(1.6)
    t.add(0, sine_sweep(1400, 500, 0.6, vol=0.2))
    for k, at in enumerate((0.6, 0.8, 1.0)):
        t.add(at, noise(0.5, vol=0.8, cutoff=0.25, seed=81 + k, attack=0.001, decay=0.12, sustain=0.0))
        t.add(at, sine_sweep(90, 30, 0.4, vol=0.6, decay=0.1, sustain=0.0))
    out["fire_B"] = t
    # Destroyer: fast screws and a short whistle / quick-firing guns.
    t = Track(0.6)
    t.add(0, square(523, 0.18, vol=0.15, duty=0.5, release=0.05))
    t.add(0.1, tremolo(noise(0.5, vol=0.3, cutoff=0.15, seed=91, attack=0.05, release=0.2), 18))
    out["move_D"] = t
    t = Track(0.7)
    for k, at in enumerate((0.0, 0.25)):
        t.add(at, sine_sweep(200, 60, 0.25, vol=0.7, attack=0.001, decay=0.06, sustain=0.0))
        t.add(at, noise(0.3, vol=0.5, cutoff=0.4, seed=95 + k, attack=0.001, decay=0.06, sustain=0.0))
    out["fire_D"] = t
    # Submarine: the sonar ping / a torpedo run and its hit.
    t = Track(1.2)
    t.add(0, bell(1318.5, 1.1, vol=0.3))
    t.add(0.5, bell(1318.5, 0.6, vol=0.08))
    out["move_S"] = t
    t = Track(1.6)
    t.add(0, tremolo(noise(0.9, vol=0.3, cutoff=0.2, seed=101, attack=0.05, release=0.1), 25, 0.9))
    t.add(0.9, sine_sweep(80, 25, 0.7, vol=0.9, attack=0.001, decay=0.2, sustain=0.0))
    t.add(0.9, noise(0.6, vol=0.6, cutoff=0.15, seed=103, attack=0.001, decay=0.15, sustain=0.0))
    out["fire_S"] = t
    # Transport: slow engine chugging and a low horn.
    t = Track(1.0)
    t.add(0, square(98, 0.45, vol=0.18, duty=0.5, attack=0.03, release=0.1))
    t.add(0, square(147, 0.45, vol=0.1, duty=0.5, attack=0.03, release=0.1))
    for k in range(4):
        t.add(0.45 + k * 0.13, noise(0.07, vol=0.3, cutoff=0.1, seed=111 + k, sustain=0.0, decay=0.03))
    out["move_T"] = t
    out["fire_T"] = out["move_T"]
    # Cruiser: a deep horn / a broadside of heavy guns.
    t = Track(0.9)
    t.add(0, square(65.4, 0.8, vol=0.2, duty=0.5, attack=0.05, release=0.2))
    t.add(0, square(98, 0.8, vol=0.12, duty=0.5, attack=0.05, release=0.2))
    out["move_R"] = t
    t = Track(1.2)
    for k, at in enumerate((0.0, 0.18, 0.36)):
        t.add(at, sine_sweep(120, 30, 0.6, vol=0.9, attack=0.001, decay=0.15, sustain=0.0))
        t.add(at, noise(0.6, vol=0.6, cutoff=0.25, seed=121 + k, attack=0.001, decay=0.12, sustain=0.0))
    out["fire_R"] = t
    # Carrier: the horn, then aircraft launching / a strike group taking off.
    t = Track(1.2)
    t.add(0, square(73.4, 0.5, vol=0.18, duty=0.5, attack=0.04, release=0.1))
    t.add(0.5, noise(0.7, vol=0.35, cutoff=0.5, seed=131, attack=0.2, release=0.4))
    out["move_C"] = t
    t = Track(1.0)
    for k in range(3):
        t.add(k * 0.2, noise(0.5, vol=0.3, cutoff=0.5, seed=141 + k, attack=0.15, release=0.3))
    out["fire_C"] = t
    return out


def _sfx() -> dict[str, Track]:
    out: dict[str, Track] = _unit_sounds()
    t = Track(0.9)  # a card snapped onto the table, then a sting
    t.add(0, noise(0.06, vol=0.6, cutoff=0.9, seed=151, attack=0.001, decay=0.015, sustain=0.0))
    t.add(0.08, noise(0.05, vol=0.4, cutoff=0.9, seed=152, attack=0.001, decay=0.012, sustain=0.0))
    sequence(t, [("R", 0.5), ("E5", 0.5), ("A5", 1.5)], 200, square, vol=0.2, duty=0.25)
    out["card"] = t
    t = Track(1.6)  # the spies' telegraph
    for k, length in enumerate((0.06, 0.06, 0.18, 0.06, 0.18, 0.18, 0.06)):
        at = sum((0.06, 0.06, 0.18, 0.06, 0.18, 0.18, 0.06)[:k]) + 0.07 * k
        t.add(at, square(880, length, vol=0.18, duty=0.5, attack=0.003, release=0.01))
    out["spy"] = t
    t = Track(0.7)  # cannon fire and explosions
    t.add(0, sine_sweep(90, 30, 0.4, vol=0.9, release=0.2))
    for k, at in enumerate((0.0, 0.12, 0.3)):
        t.add(at, noise(0.35, vol=0.6 - 0.15 * k, cutoff=0.35, seed=k + 3, decay=0.08, sustain=0.0))
    out["battle"] = t
    t = Track(0.9)  # city taken: rising fanfare
    sequence(t, [("C5", 0.5), ("E5", 0.5), ("G5", 0.5), ("C6", 1.5)], 200, square, vol=0.25, duty=0.25)
    sequence(t, [("C4", 0.5), ("E4", 0.5), ("G4", 0.5), ("C5", 1.5)], 200, triangle, vol=0.3)
    out["capture"] = t
    t = Track(1.0)  # something of ours lost
    sequence(t, [("E4", 0.75), ("C4", 0.75), ("A3", 1.5)], 150, square, vol=0.22, duty=0.5)
    sequence(t, [("A2", 3.0)], 150, triangle, vol=0.35)
    out["loss"] = t
    t = Track(1.8)  # a whole faction falls
    sequence(t, [("A4", 1), ("F4", 1), ("D4", 1), ("A3", 3)], 140, square, vol=0.22)
    sequence(t, [("D2", 6)], 140, triangle, vol=0.4)
    out["fall"] = t
    t = Track(4.5)  # nuclear strike: siren, whistle, flash, rumble
    for k in range(2):
        t.add(k * 0.8, sine_sweep(500, 900, 0.4, vol=0.35))
        t.add(k * 0.8 + 0.4, sine_sweep(900, 500, 0.4, vol=0.35))
    t.add(1.6, sine_sweep(1800, 300, 0.9, vol=0.25))
    t.add(2.5, noise(2.0, vol=1.0, cutoff=0.25, seed=7, attack=0.002, decay=0.5, sustain=0.0))
    t.add(2.5, sine_sweep(60, 25, 2.0, vol=0.9, decay=0.7, sustain=0.0))
    out["nuke"] = t
    t = Track(1.3)  # missile shot down
    t.add(0, sine_sweep(300, 1500, 0.8, vol=0.25))
    t.add(0.8, noise(0.4, vol=0.6, cutoff=0.5, seed=11, decay=0.1, sustain=0.0))
    out["intercept"] = t
    t = Track(1.5)  # gas
    t.add(0, noise(1.4, vol=0.45, cutoff=0.9, seed=13, attack=0.2, release=0.6))
    out["gas"] = t
    t = Track(1.2)  # aircraft down
    t.add(0, sine_sweep(1200, 200, 0.9, vol=0.25))
    t.add(0.9, noise(0.3, vol=0.6, cutoff=0.3, seed=17, decay=0.08, sustain=0.0))
    out["crash"] = t
    t = Track(1.6)  # truce: two soft bells
    t.add(0, bell(659.3, 1.2))
    t.add(0.35, bell(880.0, 1.2))
    out["truce"] = t
    t = Track(1.2)  # your turn
    t.add(0, bell(1046.5, 1.1, vol=0.35))
    out["turn"] = t
    t = Track(1.0)  # klaxon
    for k in range(2):
        t.add(k * 0.45, square(330, 0.35, vol=0.2, duty=0.5))
        t.add(k * 0.45, square(415, 0.35, vol=0.15, duty=0.3))
    out["alert"] = t
    return out


def _music() -> dict[str, Track]:
    out: dict[str, Track] = {}
    # Menu: the opening of Bach's Toccata in D minor (public domain), in chiptune.
    bpm = 70
    lead = [("A5", 0.25), ("G5", 0.25), ("A5", 1.5), ("R", 0.5),
            ("G5", 0.25), ("F5", 0.25), ("E5", 0.25), ("D5", 0.25), ("C#5", 1.0), ("D5", 2.0), ("R", 1),
            ("A4", 0.25), ("G4", 0.25), ("A4", 1.5), ("R", 0.5),
            ("E4", 0.5), ("F4", 0.5), ("C#4", 0.5), ("D4", 2.5), ("R", 1),
            ("A3", 0.25), ("G3", 0.25), ("A3", 1.5), ("R", 0.5),
            ("G3", 0.25), ("F3", 0.25), ("E3", 0.25), ("D3", 0.25), ("C#3", 1.0), ("D3", 3.0), ("R", 1)]
    beats = sum(b for _, b in lead)
    t = Track(beats * 60 / bpm + 0.5)
    sequence(t, lead, bpm, square, vol=0.22, duty=0.25, release=0.05)
    sequence(t, [(n[:-1] + str(int(n[-1]) - 1) if n != "R" else n, b) for n, b in lead], bpm,
             triangle, vol=0.3)
    out["menu"] = t
    # War: a minor-key march with an ostinato bass and a snare.
    bpm = 116
    melody = [("D5", 1), ("D5", 0.5), ("E5", 0.5), ("F5", 1), ("D5", 1),
              ("A5", 1.5), ("G5", 0.5), ("F5", 1), ("E5", 1),
              ("D5", 1), ("F5", 0.5), ("E5", 0.5), ("D5", 1), ("C#5", 1),
              ("D5", 3), ("R", 1),
              ("F5", 1), ("F5", 0.5), ("G5", 0.5), ("A5", 1), ("F5", 1),
              ("Bb5", 1.5), ("A5", 0.5), ("G5", 1), ("F5", 1),
              ("E5", 1), ("G5", 0.5), ("F5", 0.5), ("E5", 1), ("C#5", 1),
              ("D5", 3), ("R", 1)]
    bass_bar = {"D": [("D2", 1), ("A2", 1), ("D3", 1), ("A2", 1)],
                "Bb": [("Bb1", 1), ("F2", 1), ("Bb2", 1), ("F2", 1)],
                "A": [("A1", 1), ("E2", 1), ("A2", 1), ("E2", 1)],
                "F": [("F2", 1), ("C3", 1), ("F3", 1), ("C3", 1)],
                "G": [("G1", 1), ("D2", 1), ("G2", 1), ("D2", 1)]}
    bass = []
    for chord in ("D", "Bb", "A", "D", "F", "G", "A", "D"):
        bass += bass_bar[chord]
    t = Track(32 * 60 / bpm + 0.3)
    sequence(t, melody, bpm, square, vol=0.17, duty=0.25, release=0.03)
    sequence(t, bass, bpm, triangle, vol=0.35, release=0.03)
    drums(t, bpm, 8)
    out["war"] = t
    # Tension: a heartbeat, the ticking of the clock and a low drone.
    t = Track(12.0)
    t.add(0, triangle(73.4, 12.0, vol=0.25, attack=1.0, release=1.0))
    t.add(0, triangle(77.8, 12.0, vol=0.12, attack=1.0, release=1.0))
    for k in range(24):
        t.add(k * 0.5, noise(0.02, vol=0.35, cutoff=1.0, seed=k, sustain=0.0, decay=0.005))
    for k in range(12):
        t.add(k + 0.0, sine_sweep(70, 45, 0.12, vol=0.8, release=0.05))
        t.add(k + 0.22, sine_sweep(60, 40, 0.12, vol=0.6, release=0.05))
    out["tension"] = t
    # Victory: a major fanfare.
    bpm = 132
    t = Track(5.5)
    sequence(t, [("G4", 0.5), ("C5", 0.5), ("E5", 0.5), ("G5", 1.5), ("E5", 0.5), ("G5", 3),
                 ("A5", 0.5), ("G5", 0.5), ("F5", 0.5), ("E5", 0.5), ("D5", 0.5), ("C5", 3)],
             bpm, square, vol=0.22, duty=0.25)
    sequence(t, [("C3", 4), ("G2", 4), ("C3", 4)], bpm, triangle, vol=0.35)
    drums(t, bpm, 3, pattern="k.k.ksss")
    out["victory"] = t
    # Defeat: a slow lament.
    bpm = 60
    t = Track(8.5)
    sequence(t, [("A4", 1), ("G4", 1), ("F4", 1), ("E4", 2), ("D4", 3)], bpm, square, vol=0.18, duty=0.5)
    sequence(t, [("D2", 4), ("A1", 4)], bpm, triangle, vol=0.35)
    out["defeat"] = t
    # Midnight: the wind over a dead world.
    t = Track(9.0)
    t.add(0, noise(9.0, vol=0.5, cutoff=0.04, seed=99, attack=2.0, release=3.0))
    t.add(0, sine_sweep(110, 30, 9.0, vol=0.35, attack=1.0, release=3.0))
    out["midnight"] = t
    # Kalinka (I. Larionov, 1860; public domain), from the MIDI arrangement
    # by V. Diomin that the player supplied: the fast refrain «Калинка, калинка, калинка
    # моя» (trumpet line) and the slow verse «Ах, под сосною, под зелёною»
    # (accordion line) over the original bass. Beats are quarters; the
    # tempo changes as in the arrangement: the refrain runs, then a pause
    # and the broad verse, and the loop starts again from the refrain.
    refrain = [
        ("C#5", 0.75), ("R", 0.25), ("B4", 0.5), ("R", 0.5), ("G#4", 0.25), ("R", 0.25),
        ("A4", 0.25), ("R", 0.25), ("B4", 0.5), ("R", 0.5), ("G#4", 0.25), ("R", 0.25),
        ("A4", 0.25), ("R", 0.25), ("B4", 0.5), ("C#5", 0.25), ("B4", 0.25), ("A4", 0.25),
        ("R", 0.25), ("G#4", 0.25), ("R", 0.25), ("F#4", 0.75), ("R", 0.25), ("C#5", 0.25),
        ("R", 0.25), ("C#5", 0.25), ("R", 0.25), ("B4", 0.5), ("R", 0.25), ("A4", 0.25),
        ("G#4", 0.25), ("R", 0.25), ("A4", 0.25), ("R", 0.25), ("B4", 0.75), ("R", 0.25),
        ("G#4", 0.25), ("R", 0.25), ("A4", 0.25), ("R", 0.25), ("B4", 0.5), ("C#5", 0.25),
        ("B4", 0.25), ("R", 0.5), ("G#4", 0.25), ("R", 0.25), ("F#4", 0.75), ("R", 0.25),
        ("C#5", 0.25), ("R", 0.25), ("C#5", 0.25), ("R", 0.25), ("B4", 0.75), ("R", 0.25),
        ("G#4", 0.25), ("R", 0.25), ("A4", 0.25), ("R", 0.25), ("B4", 0.75), ("R", 0.25),
        ("G#4", 0.25), ("R", 0.25), ("A4", 0.25), ("R", 0.25), ("B4", 0.5), ("C#5", 0.25),
        ("B4", 0.25), ("R", 0.5), ("G#4", 0.25), ("R", 0.25), ("F#4", 0.25), ("R", 0.75),
        ("C#5", 0.25), ("R", 0.25), ("C#5", 0.25), ("R", 0.25), ("B4", 0.5), ("R", 0.25),
        ("A4", 0.25), ("G#4", 0.25), ("R", 0.25), ("A4", 0.25), ("R", 0.25), ("B4", 0.5),
        ("R", 0.5), ("G#4", 0.25), ("R", 0.25), ("A4", 0.25), ("R", 0.25), ("B4", 0.5),
        ("C#5", 0.25), ("B4", 0.25), ("R", 0.5), ("G#4", 0.25), ("R", 0.25)]
    verse = [
        ("F#5", 1.5), ("R", 0.25), ("G#5", 0.25), ("E5", 2), ("C#6", 1), ("R", 0.25),
        ("E6", 0.75), ("R", 0.25), ("D6", 0.25), ("D6", 0.5), ("C#6", 0.5), ("B5", 0.5),
        ("A5", 1.5), ("B5", 0.25), ("A5", 0.25), ("R", 2), ("C#6", 1), ("E6", 1), ("D6", 0.75),
        ("E6", 0.25), ("C#6", 0.5), ("B5", 0.5), ("A5", 1.5), ("R", 0.25), ("B5", 0.25),
        ("E5", 1.5), ("R", 0.5), ("F#5", 1.75), ("R", 0.25), ("F#5", 1), ("G#5", 1), ("B5", 1),
        ("R", 0.25), ("A5", 1), ("G#5", 0.25), ("A5", 0.25), ("G#5", 0.25), ("F#5", 0.25),
        ("R", 0.25), ("G#5", 0.25), ("F#5", 0.25), ("E5", 2), ("R", 2), ("E6", 1), ("E5", 1),
        ("F#5", 1), ("G#5", 0.5), ("R", 0.5), ("C#6", 1), ("E6", 1), ("D6", 0.5), ("E6", 0.25),
        ("D6", 0.25), ("C#6", 0.5), ("B5", 0.5), ("A5", 1.5), ("B5", 0.25), ("A5", 0.25),
        ("E5", 2), ("C#6", 1), ("E6", 1), ("D6", 0.75), ("E6", 0.25), ("C#6", 0.5),
        ("B5", 0.5), ("A5", 2), ("E5", 1.5), ("R", 0.5), ("F#5", 1.75), ("R", 0.25),
        ("F#5", 1), ("G#5", 1), ("B5", 1), ("A5", 1), ("G#5", 0.5), ("R", 0.25), ("A5", 0.25),
        ("F#5", 0.5), ("R", 0.5)]
    bass = [
        ("R", 1), ("C#2", 0.75), ("R", 0.25), ("G#2", 0.5), ("R", 0.5), ("C#2", 0.5),
        ("R", 0.5), ("G#2", 0.5), ("R", 0.5), ("C#2", 0.75), ("R", 0.25), ("G#2", 0.5),
        ("R", 0.5), ("F#2", 0.5), ("R", 0.5), ("F#2", 0.5), ("R", 0.5), ("C#2", 0.75),
        ("R", 0.25), ("G#2", 0.5), ("R", 0.5), ("C#2", 0.75), ("R", 0.25), ("G#2", 0.5),
        ("R", 0.5), ("C#2", 0.75), ("R", 0.25), ("G#2", 0.75), ("R", 0.25), ("F#2", 0.5),
        ("R", 0.5), ("F#2", 0.75), ("R", 0.25), ("C#2", 0.75), ("R", 0.25), ("G#2", 0.75),
        ("R", 0.25), ("C#2", 0.75), ("R", 0.25), ("G#2", 0.5), ("R", 0.5), ("C#2", 0.75),
        ("R", 0.25), ("G#2", 0.5), ("R", 0.5), ("F#2", 0.75), ("R", 0.25), ("F#2", 0.5),
        ("R", 0.5), ("C#2", 0.75), ("R", 0.25), ("G#2", 0.5), ("R", 0.5), ("C#2", 0.75),
        ("R", 0.25), ("G#2", 0.5), ("R", 0.5), ("C#2", 0.75), ("R", 0.25), ("G#2", 0.5),
        ("R", 0.5), ("F#2", 1.75), ("R", 0.25), ("E2", 1.75), ("R", 0.25), ("A2", 1.75),
        ("R", 0.25), ("E2", 2), ("A2", 2), ("E2", 2), ("A2", 2), ("E2", 2), ("A2", 1.75),
        ("R", 0.25), ("E2", 2), ("D2", 1.75), ("R", 0.25), ("D2", 1), ("C#2", 1), ("B1", 4),
        ("E2", 3.75), ("R", 0.25), ("E2", 1), ("D2", 1), ("C#2", 1), ("B1", 1), ("A2", 1.75),
        ("R", 0.25), ("E2", 2), ("A2", 2), ("E2", 2), ("A2", 2), ("E2", 2), ("A2", 2),
        ("E2", 2), ("D2", 1.75), ("R", 0.25), ("D2", 1), ("C#2", 1), ("B1", 2), ("G#1", 2)]
    tempo = [(0, 174), (31, 99), (33, 59), (35, 119)]   # (beat, bpm)
    beats = sum(b for _, b in bass)
    t = Track(beat_time(tempo, beats) + 0.3)
    sequence(t, refrain + verse, tempo, square, vol=0.2, duty=0.25, release=0.03)
    sequence(t, refrain, tempo, square, vol=0.07, duty=0.5, release=0.03)  # doubled refrain
    sequence(t, bass, tempo, triangle, vol=0.24, release=0.03)
    # the refrain is danced: kick and snare on the beats (bars start at beat 1)
    drums(t, 174, 7, start=beat_time(tempo, 1), pattern="k.s.k.s.")
    out["kalinka"] = t
    # State Anthem of the USSR (A. V. Alexandrov, 1939-1944; public domain).
    # Melody in C major as in the official score: pickup, the verse
    # «Союз нерушимый республик свободных» and the refrain «Славься,
    # Отечество наше свободное» with its two endings. Beats are quarters.
    bpm = 76
    melody = [
        ("G4", 0.5),
        # «Союз нерушимый республик свободных / Сплотила навеки Великая Русь»
        ("C5", 1), ("G4", 0.75), ("A4", 0.25), ("B4", 1), ("E4", 0.5), ("E4", 0.5),
        ("A4", 1), ("G4", 0.75), ("F4", 0.25), ("G4", 1), ("C4", 0.5), ("C4", 0.5),
        ("D4", 1), ("D4", 0.75), ("E4", 0.25), ("F4", 1), ("F4", 0.75), ("G4", 0.25),
        ("A4", 1), ("B4", 0.5), ("C5", 0.5), ("D5", 1.5), ("G4", 0.5),
        # «Да здравствует созданный волей народов / Единый, могучий Советский Союз»
        ("E5", 1), ("D5", 0.75), ("C5", 0.25), ("D5", 1), ("B4", 0.5), ("G4", 0.5),
        ("C5", 1), ("B4", 0.75), ("A4", 0.25), ("B4", 1), ("E4", 0.5), ("E4", 0.5),
        ("A4", 1), ("G4", 0.75), ("F4", 0.25), ("G4", 1), ("C4", 0.5), ("C4", 0.5),
        ("C5", 1), ("B4", 0.75), ("A4", 0.25), ("G4", 1.5), ("R", 0.5),
        # «Славься, Отечество наше свободное, / Дружбы народов надёжный оплот!»
        ("E5", 2), ("D5", 0.5), ("C5", 0.5), ("B4", 0.5), ("C5", 0.5),
        ("D5", 1.5), ("G4", 0.5), ("G4", 1), ("R", 1),
        ("C5", 2), ("B4", 0.5), ("A4", 0.5), ("G4", 0.5), ("A4", 0.5),
        ("B4", 1.5), ("E4", 0.5), ("E4", 0.5), ("G4", 0.5), ("A4", 0.5), ("B4", 0.5),
        # «Знамя советское, знамя народное / Пусть от победы к победе ведёт!»
        ("C5", 1), ("A4", 0.75), ("B4", 0.25), ("C5", 1), ("A4", 0.75), ("B4", 0.25),
        ("C5", 1), ("A4", 0.5), ("C5", 0.5), ("F5", 2),
        ("F5", 2), ("E5", 0.5), ("D5", 0.5), ("C5", 0.5), ("D5", 0.5),
        ("E5", 1.5), ("C5", 0.5), ("C5", 2),
        ("D5", 2), ("C5", 0.5), ("B4", 0.5), ("A4", 0.5), ("B4", 0.5),
        ("C5", 1.5), ("A4", 0.5), ("A4", 2),
        ("C5", 1), ("B4", 0.75), ("A4", 0.25), ("G4", 1), ("C4", 0.5), ("C4", 0.5),
        # last ending: «...ведёт!» broadening to the tonic
        ("C5", 1), ("B4", 0.75), ("A4", 0.25), ("G4", 2),
        ("G4", 2), ("A4", 1), ("B4", 1), ("C5", 3), ("R", 1),
    ]
    # One chord per half bar (root, fifth), following the official harmony.
    chords = ["C", "E", "F", "C", "D", "G", "F", "G",       # verse, line 1
              "C", "G", "A", "E", "F", "C", "F", "G",       # verse, line 2
              "C", "C", "G", "G", "A", "A", "E", "E",       # refrain
              "F", "F", "F", "F", "D", "G", "C", "C",
              "G", "G", "A", "A", "F", "C", "F", "G",
              "G", "G", "C", "C"]
    fifth = {"C": "G", "D": "A", "E": "B", "F": "C", "G": "D", "A": "E"}
    bass = [("G2", 0.5)]
    for root in chords:
        low = "1" if root in "AB" else "2"
        bass += [(root + low, 1), (fifth[root] + ("2" if root in "FGAB" else low), 1)]
    beats = sum(b for _, b in melody)
    t = Track(beats * 60 / bpm + 0.5)
    sequence(t, melody, bpm, square, vol=0.2, duty=0.25, release=0.04)
    sequence(t, melody, bpm, square, vol=0.06, duty=0.5, release=0.04)  # chorus doubling
    sequence(t, bass, bpm, triangle, vol=0.32, release=0.05)
    out["anthem"] = t
    return out


def generate(cache: Path = CACHE) -> None:
    """Write every effect and tune as a WAV file (once; later runs reuse them)."""
    cache.mkdir(parents=True, exist_ok=True)
    for builder in (_sfx, _music):
        names = _SFX_NAMES if builder is _sfx else _MUSIC_NAMES
        if all((cache / f"{n}.wav").exists() for n in names):
            continue
        for name, track in builder().items():
            path = cache / f"{name}.wav"
            tmp = path.with_suffix(".tmp")
            with wave.open(str(tmp), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                # Music sits under the effects.
                w.writeframes(track.pcm(0.9 if builder is _sfx else 0.45))
            tmp.replace(path)


UNIT_KINDS = "IAFBDSTRC"
_SFX_NAMES = ("battle", "capture", "loss", "fall", "nuke", "intercept", "gas", "crash",
              "truce", "turn", "alert", "card", "spy") + tuple(
    f"{what}_{k}" for k in UNIT_KINDS for what in ("move", "fire"))
_MUSIC_NAMES = ("menu", "war", "tension", "victory", "defeat", "midnight",
                 "kalinka", "anthem")


# ----------------------------------------------------------------- playback
def find_player() -> list[str] | None:
    for cmd in (["afplay"], ["paplay"], ["pw-play"], ["aplay", "-q"],
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def _settings() -> dict:
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _sync_audio(data: dict) -> None:
    """Keep the old "audio" key in step with the new music/effects choices."""
    music = data.get("music", "auto")
    effects = data.get("effects", True)
    data["audio"] = "all" if effects and music != "off" else ("sfx" if effects else "off")


def load_music() -> str:
    """The chosen background music, or "auto" when nothing was chosen yet."""
    data = _settings()
    if "music" in data:
        music = {"cossack": "kalinka"}.get(data["music"], data["music"])  # renamed tune
        return music if music in MUSIC_CHOICES else "auto"
    mode = data.get("audio", "all")  # legacy: the old all/sfx/off mode
    return "off" if mode in ("sfx", "off") else "auto"


def save_music(choice: str) -> None:
    if choice not in MUSIC_CHOICES:
        return
    data = _settings()
    data["music"] = choice
    _sync_audio(data)
    _save(data)


def load_effects() -> bool:
    """Whether the sound effects are on (legacy "audio" mode migrates here)."""
    data = _settings()
    if "effects" in data:
        return bool(data["effects"])
    return data.get("audio", "all") != "off"


def save_effects(on: bool) -> None:
    data = _settings()
    data["effects"] = on
    _sync_audio(data)
    _save(data)


class Audio:
    """Plays effects and music in the background without ever blocking or
    failing the game: any problem just means silence (or the bell)."""

    MAX_EFFECTS = 3

    def __init__(self, mode: str | None = None, music: str | None = None,
                 effects: bool | None = None, cache: Path = CACHE, bell=None):
        if mode is not None:                      # --audio all|sfx|off
            self.music_choice = "off" if mode in ("sfx", "off") else "auto"
            self.effects = mode != "off"
        else:
            self.music_choice = music if music is not None else load_music()
            self.effects = effects if effects is not None else load_effects()
        self.cache = cache
        self.bell = bell              # fallback, e.g. curses.beep
        self.player = find_player()
        self.ready = threading.Event()
        self.running: list[subprocess.Popen] = []
        self.track: str | None = None     # what is playing
        self.wanted: str | None = None    # what the game asked for
        self.music_proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        if self.player is not None and (self.effects or self.music_choice != "off"):
            self._start()
        self.loop_thread = threading.Thread(target=self._loop, daemon=True)
        self.loop_thread.start()

    def _start(self) -> None:
        if getattr(self, "_generating", False):
            return
        self._generating = True

        def work():
            try:
                generate(self.cache)
                self.ready.set()
            except OSError:
                self.player = None
        threading.Thread(target=work, daemon=True).start()

    @property
    def available(self) -> bool:
        return self.player is not None

    def _spawn(self, name: str) -> subprocess.Popen | None:
        path = self.cache / f"{name}.wav"
        if not path.exists():
            return None
        try:
            return subprocess.Popen(self.player + [str(path)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return None

    def sfx(self, name: str, force: bool = False) -> None:
        """Play one effect. With ``force`` (used by the end-of-turn newsreel)
        the older effects are cut short so the important sound is heard."""
        if not self.effects:
            return
        if self.player is None or not self.ready.is_set():
            if self.bell and name in ("nuke", "capture", "fall", "turn", "alert", "loss"):
                try:
                    self.bell()
                except Exception:  # noqa: BLE001 - the bell is best effort
                    pass
            return
        with self.lock:
            self.running = [p for p in self.running if p.poll() is None]
            if force:
                for p in self.running:
                    p.terminate()
                self.running = []
            if len(self.running) >= self.MAX_EFFECTS:
                return
            proc = self._spawn(name)
            if proc is not None:
                self.running.append(proc)

    def music(self, track: str | None) -> None:
        """Switch the background music (None = silence). The chosen tune, if
        any, wins over the track the game suggests for the moment."""
        self.wanted = track
        if self.music_choice == "off":
            track = None
        elif self.music_choice != "auto":
            track = self.music_choice
        with self.lock:
            if track == self.track:
                return
            self.track = track
            self._stop_music()

    def select_music(self, choice: str) -> None:
        """Pick a tune from MUSIC_CHOICES and keep it for the next games."""
        if choice not in MUSIC_CHOICES:
            return
        self.music_choice = choice
        save_music(choice)
        if self.player is not None and choice != "off":
            self._start()
        self.music(self.wanted)

    def toggle_effects(self) -> bool:
        """Mute or unmute the sound effects; returns the new state."""
        self.effects = not self.effects
        save_effects(self.effects)
        if self.effects and self.player is not None:
            self._start()
        self.music(self.wanted)
        return self.effects

    def _stop_music(self) -> None:
        if self.music_proc is not None and self.music_proc.poll() is None:
            self.music_proc.terminate()
        self.music_proc = None

    def _loop(self) -> None:
        """Start the wanted tune when it is ready, and loop the looping ones."""
        played_once: str | None = None
        while not self.stopping.wait(0.3):
            if self.player is None or not self.ready.is_set():
                continue
            with self.lock:
                track = self.track
                if track is None:
                    played_once = None
                    continue
                running = self.music_proc is not None and self.music_proc.poll() is None
                if running:
                    continue
                if track not in LOOPING and played_once == track:
                    continue
                self.music_proc = self._spawn(track)
                played_once = track

    def close(self) -> None:
        self.stopping.set()
        with self.lock:
            self._stop_music()
            for p in self.running:
                if p.poll() is None:
                    p.terminate()
            self.running.clear()


class EscapeAudio:
    """Audio for the web terminal: instead of playing anything, the client
    writes an invisible escape sequence (OSC 7777) that the browser page
    catches and plays with the Web Audio API. Same interface as Audio."""

    available = True

    def __init__(self, write=None):
        self.write = write or self._stdout
        self.music_choice = load_music()
        self.effects = load_effects()
        self.track: str | None = None
        self.wanted: str | None = None

    @staticmethod
    def _stdout(data: bytes) -> None:
        import os
        try:
            os.write(1, data)
        except OSError:
            pass

    def _send(self, *parts: str) -> None:
        self.write(("\x1b]7777;" + ";".join(parts) + "\x07").encode("ascii"))

    def sfx(self, name: str, force: bool = False) -> None:
        if self.effects and name.replace("_", "").isalnum():
            self._send("sfx", name, "1" if force else "0")

    def music(self, track: str | None) -> None:
        self.wanted = track
        if self.music_choice == "off":
            track = None
        elif self.music_choice != "auto":
            track = self.music_choice
        if track == self.track:
            return
        self.track = track
        self._send("music", track or "", "1" if track in LOOPING else "0")

    def select_music(self, choice: str) -> None:
        if choice in MUSIC_CHOICES:
            self.music_choice = choice
            save_music(choice)
            self.music(self.wanted)

    def toggle_effects(self) -> bool:
        self.effects = not self.effects
        save_effects(self.effects)
        return self.effects

    def close(self) -> None:
        self._send("music", "", "0")
