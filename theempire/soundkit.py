"""The modern sound style: effects and music with a little studio inside.

The retro style of audio.py is the 8-bit home computer of Theatre Europe:
square and triangle waves and bare noise. This one is still synthesised in
pure Python, but like a modern strategy game: band-limited saws and
detuned "supersaw" pads, filters that open and close, layered explosions
(the crack, the body, the sub drop, the debris), a hall reverb, soft
saturation and the kick pumping the bass. Same names and same melodies
(audio.py's tunes): only the instruments change.
"""

from __future__ import annotations

import math
import random

from theempire.audio import (ANTHEM_CHORDS, ANTHEM_FIFTH, ANTHEM_MELODY, KALINKA_BASS, KALINKA_REFRAIN,
                             KALINKA_TEMPO, KALINKA_VERSE, MENU_LEAD, RATE, WAR_BASS_BAR, WAR_CHORDS,
                             WAR_MELODY, Track, beat_time, freq)

TAU = 2 * math.pi


# ------------------------------------------------------------ building blocks
def n_of(seconds: float) -> int:
    return max(1, int(seconds * RATE))


def adsr(n: int, a: float = 0.005, d: float = 0.1, s: float = 0.7, r: float = 0.1) -> list[float]:
    """Attack, decay to the sustain level, release at the end (seconds)."""
    na, nd, nr = max(1, int(a * RATE)), max(1, int(d * RATE)), max(1, int(r * RATE))
    out = [0.0] * n
    for i in range(n):
        if i < na:
            v = i / na
        elif i < na + nd:
            v = 1 - (1 - s) * (i - na) / nd
        else:
            v = s
        if i > n - nr:
            v *= max(0.0, (n - i) / nr)
        out[i] = v
    return out


def decay(n: int, tau: float, attack: float = 0.001) -> list[float]:
    """A percussive envelope: a quick rise and an exponential fall."""
    na = max(1, int(attack * RATE))
    k = math.exp(-1.0 / max(1.0, tau * RATE))
    out, v = [0.0] * n, 1.0
    for i in range(n):
        if i < na:
            out[i] = i / na
        else:
            out[i] = v
            v *= k
    return out


def mul(a: list[float], b: list[float]) -> list[float]:
    return [x * y for x, y in zip(a, b)]


def gain(a: list[float], g: float) -> list[float]:
    return [x * g for x in a]


def sine(f, n: int, phase: float = 0.0) -> list[float]:
    """A sine; ``f`` is a frequency or a list of them (a glide)."""
    out, ph = [0.0] * n, phase
    if isinstance(f, (int, float)):
        step = TAU * f / RATE
        for i in range(n):
            out[i] = math.sin(ph)
            ph += step
        return out
    for i in range(n):
        out[i] = math.sin(ph)
        ph += TAU * f[i] / RATE
    return out


def glide(f0: float, f1: float, n: int, curve: float = 1.0) -> list[float]:
    """A frequency moving from f0 to f1 (exponentially, as pitch does)."""
    if n <= 1:
        return [f0] * n
    r = math.log(f1 / f0)
    return [f0 * math.exp(r * (i / (n - 1)) ** curve) for i in range(n)]


def saw(f: float, n: int, phase: float = 0.0) -> list[float]:
    """A band-limited sawtooth (polyBLEP: no harsh aliasing)."""
    dt = f / RATE
    out, t = [0.0] * n, phase % 1.0
    for i in range(n):
        v = 2.0 * t - 1.0
        if t < dt:
            x = t / dt
            v -= x + x - x * x - 1.0
        elif t > 1.0 - dt:
            x = (t - 1.0) / dt
            v -= x * x + x + x + 1.0
        out[i] = v
        t += dt
        if t >= 1.0:
            t -= 1.0
    return out


def supersaw(f: float, n: int, voices: int = 5, detune: float = 0.011, seed: int = 1) -> list[float]:
    """Several saws a little out of tune with each other: the wide modern pad."""
    rng = random.Random(seed)
    out = [0.0] * n
    for k in range(voices):
        spread = (k - (voices - 1) / 2) / max(1, (voices - 1) / 2)
        for i, v in enumerate(saw(f * (1 + detune * spread), n, rng.random())):
            out[i] += v
    return gain(out, 1.0 / voices ** 0.5)


def white(n: int, seed: int = 1) -> list[float]:
    rnd = random.Random(seed).random
    return [rnd() * 2 - 1 for _ in range(n)]


def lowpass(x: list[float], cutoff, res: float = 0.0) -> list[float]:
    """A 12 dB/oct low-pass (two one-poles with a touch of resonance);
    ``cutoff`` in Hz, a number or a list (a sweep)."""
    out = [0.0] * len(x)
    a = b = 0.0
    fixed = isinstance(cutoff, (int, float))
    g = 1 - math.exp(-TAU * min(cutoff, RATE * 0.45) / RATE) if fixed else 0.0
    for i, v in enumerate(x):
        if not fixed:
            g = 1 - math.exp(-TAU * min(cutoff[i], RATE * 0.45) / RATE)
        a += g * (v - a - res * (b - a))
        b += g * (a - b)
        out[i] = b
    return out


def highpass(x: list[float], cutoff: float) -> list[float]:
    g = 1 - math.exp(-TAU * cutoff / RATE)
    out, lp = [0.0] * len(x), 0.0
    for i, v in enumerate(x):
        lp += g * (v - lp)
        out[i] = v - lp
    return out


def bandpass(x: list[float], low: float, high: float) -> list[float]:
    return lowpass(highpass(x, low), high)


def drive(x: list[float], amount: float = 2.0) -> list[float]:
    """Soft saturation: weight and warmth, no hard clipping."""
    t = math.tanh(amount)
    return [math.tanh(v * amount) / t for v in x]


def reverb(x: list[float], mix: float = 0.25, size: float = 1.0, damp: float = 0.35,
           tail: float = 1.5) -> list[float]:
    """A small hall (Schroeder: four combs and two all-passes), returned
    with ``tail`` seconds more so the echo can fade."""
    n = len(x) + int(tail * RATE)
    src = x + [0.0] * (n - len(x))
    wet = [0.0] * n
    for delay in (1557, 1617, 1491, 1422):
        d = int(delay * size * RATE / 44100)
        buf, idx, filt = [0.0] * d, 0, 0.0
        fb = 0.78
        for i in range(n):
            y = buf[idx]
            filt = y * (1 - damp) + filt * damp
            buf[idx] = src[i] + filt * fb
            idx += 1
            if idx == d:
                idx = 0
            wet[i] += y
    for delay in (225, 556):
        d = int(delay * RATE / 44100)
        buf, idx = [0.0] * d, 0
        for i in range(n):
            y = buf[idx]
            v = wet[i]
            buf[idx] = v + y * 0.5
            wet[i] = y - v * 0.5
            idx += 1
            if idx == d:
                idx = 0
    return [s * (1 - mix) + w * mix * 0.25 for s, w in zip(src, wet)]


def pad(x: list[float], seconds: float) -> list[float]:
    return x + [0.0] * max(0, n_of(seconds) - len(x))


# ------------------------------------------------------------------- voices
def lead(f: float, seconds: float, vol: float = 0.3, bright: float = 2600.0) -> list[float]:
    """A brassy lead: two saws, the filter opening at each note."""
    n = n_of(seconds)
    raw = [a + 0.6 * b for a, b in zip(saw(f, n), saw(f * 1.004, n, 0.3))]
    env = adsr(n, 0.02, 0.25, 0.75, min(0.12, seconds * 0.4))
    cut = [400 + bright * e for e in adsr(n, 0.03, 0.3, 0.45, 0.1)]
    return mul(lowpass(raw, cut, 0.3), gain(env, vol))


def brass(f: float, seconds: float, vol: float = 0.3) -> list[float]:
    """Low brass for the big themes: darker, slower to open."""
    n = n_of(seconds)
    raw = [a + b + 0.5 * c for a, b, c in zip(saw(f, n), saw(f * 1.006, n, 0.5), saw(f / 2, n, 0.2))]
    env = adsr(n, 0.06, 0.3, 0.85, min(0.2, seconds * 0.4))
    cut = [250 + 1500 * e for e in adsr(n, 0.12, 0.4, 0.6, 0.15)]
    return mul(lowpass(raw, cut, 0.2), gain(env, vol * 0.5))


def pluck(f: float, seconds: float, vol: float = 0.3) -> list[float]:
    """A plucked synth: bright attack, quick fall (arpeggios, Kalinka)."""
    n = n_of(seconds)
    raw = saw(f, n)
    cut = [300 + 4200 * e for e in decay(n, 0.09)]
    return mul(lowpass(raw, cut, 0.4), gain(decay(n, max(0.12, seconds * 0.8), 0.002), vol))


def bass(f: float, seconds: float, vol: float = 0.35) -> list[float]:
    """A round synth bass: saw plus sub sine, filtered."""
    n = n_of(seconds)
    raw = [0.7 * a + 0.8 * b for a, b in zip(saw(f, n), sine(f / 2 if f > 80 else f, n))]
    cut = [180 + 900 * e for e in decay(n, 0.12)]
    return mul(drive(lowpass(raw, cut, 0.2), 1.5), gain(adsr(n, 0.004, 0.1, 0.8, 0.03), vol))


def strings(f: float, seconds: float, vol: float = 0.2) -> list[float]:
    """A warm pad of detuned saws, slow to swell."""
    n = n_of(seconds)
    return mul(lowpass(supersaw(f, n, 5, 0.009, int(f)), 1400 + f * 0.5),
               gain(adsr(n, min(0.6, seconds * 0.3), 0.2, 0.9, min(0.8, seconds * 0.3)), vol))


def epiano(f: float, seconds: float, vol: float = 0.3) -> list[float]:
    """An FM electric piano (the lament)."""
    n = n_of(seconds)
    env = decay(n, 1.2, 0.003)
    mod = decay(n, 0.25, 0.001)
    out, ph, mp = [0.0] * n, 0.0, 0.0
    step, mstep = TAU * f / RATE, TAU * f * 2 / RATE
    for i in range(n):
        out[i] = math.sin(ph + 1.8 * mod[i] * math.sin(mp)) * env[i] * vol
        ph += step
        mp += mstep
    return out


def chord(track: Track, start: float, notes: list[str], seconds: float, voice=strings, vol: float = 0.18):
    for name in notes:
        track.add(start, voice(freq(name), seconds, vol))


# ------------------------------------------------------------------ drums
def kick(vol: float = 0.9) -> list[float]:
    n = n_of(0.45)
    body = mul(sine(glide(150, 42, n, 0.35), n), decay(n, 0.12))
    click = mul(highpass(white(n_of(0.012), 3), 2000), decay(n_of(0.012), 0.003))
    out = drive(body, 1.8)
    for i, v in enumerate(click):
        out[i] += v * 0.5
    return gain(out, vol)


def snare(vol: float = 0.5, seed: int = 5) -> list[float]:
    n = n_of(0.3)
    tone = mul(sine(glide(240, 170, n), n), decay(n, 0.05))
    hiss = mul(bandpass(white(n, seed), 1200, 7000), decay(n, 0.09))
    return [vol * (0.6 * a + b) for a, b in zip(tone, hiss)]


def hat(vol: float = 0.18, open_: bool = False, seed: int = 9) -> list[float]:
    n = n_of(0.25 if open_ else 0.06)
    return mul(highpass(white(n, seed), 7000), gain(decay(n, 0.08 if open_ else 0.015), vol))


def taiko(vol: float = 0.8, pitch: float = 90) -> list[float]:
    """A big low drum: the heartbeat of cinematic war music."""
    n = n_of(0.9)
    body = mul(sine(glide(pitch * 1.6, pitch * 0.7, n, 0.3), n), decay(n, 0.28))
    skin = mul(lowpass(white(n, int(pitch)), 900), decay(n, 0.05))
    return gain(drive([a + 0.5 * b for a, b in zip(body, skin)], 1.4), vol)


def crash(vol: float = 0.35, seed: int = 11) -> list[float]:
    n = n_of(2.2)
    return mul(highpass(white(n, seed), 4000), gain(decay(n, 0.7, 0.002), vol))


def timpani(f: float, vol: float = 0.6) -> list[float]:
    n = n_of(1.4)
    tone = [math.sin(TAU * f * i / RATE) + 0.4 * math.sin(TAU * f * 1.5 * i / RATE) for i in range(n)]
    return gain(mul(lowpass(tone, 700), decay(n, 0.45, 0.004)), vol)


def pump(x: list[float], beat: float, start: float = 0.0, depth: float = 0.6) -> list[float]:
    """Sidechain: the sound ducks at every beat, as if the kick pushed it away."""
    period = beat * RATE
    out = [0.0] * len(x)
    for i, v in enumerate(x):
        ph = ((i - start * RATE) % period) / period
        out[i] = v * (1 - depth * math.exp(-ph * 6))
    return out


# ------------------------------------------------------------- sound design
def explosion(size: float = 1.0, seed: int = 1, distance: float = 0.0) -> list[float]:
    """Crack, body, sub drop and debris; far away, the highs are gone."""
    n = n_of(1.4 + 1.6 * size)
    crack = mul(highpass(white(n_of(0.03), seed), 1500), decay(n_of(0.03), 0.008))
    body = mul(lowpass(white(n, seed + 1), glide(5000 * (1 - distance * 0.7), 150, n, 0.5)),
               decay(n, 0.25 + 0.35 * size, 0.002))
    sub = mul(sine(glide(90, 28, n, 0.5), n), decay(n, 0.35 + 0.4 * size, 0.003))
    rng = random.Random(seed + 2)
    debris = [0.0] * n
    for _ in range(int(25 * size)):
        at = int(rng.uniform(0.1, 0.9) * n)
        length = n_of(0.02)
        for i, v in enumerate(mul(highpass(white(length, rng.randrange(9999)), 3000), decay(length, 0.004))):
            if at + i < n:
                debris[at + i] += v * rng.uniform(0.05, 0.18) * (1 - at / n)
    out = [0.0] * n
    for i in range(n):
        out[i] = 0.9 * body[i] + 1.1 * sub[i] + debris[i]
    for i, v in enumerate(crack):
        out[i] += v * (0.8 - distance * 0.6)
    return reverb(drive(out, 1.6 + size), mix=0.25, size=1.2, tail=0.8)


def gunshot(seed: int = 1, heavy: float = 0.0) -> list[float]:
    """A rifle crack (light) or a cannon (heavy): the bang and its slap."""
    n = n_of(0.25 + heavy * 0.9)
    snap = mul(highpass(white(n, seed), 1800 - 1400 * heavy), decay(n, 0.02 + 0.05 * heavy))
    thump = mul(sine(glide(160 - 60 * heavy, 45, n, 0.4), n), decay(n, 0.04 + 0.2 * heavy))
    return [0.7 * a + (0.5 + heavy) * b for a, b in zip(snap, thump)]


def engine(f: float, seconds: float, rough: float = 0.3, seed: int = 1) -> list[float]:
    """A combustion engine: a low pulse train, a little unsteady."""
    n = n_of(seconds)
    rng = random.Random(seed)
    jitter = lowpass([rng.uniform(-1, 1) for _ in range(n)], 6)
    fs = [f * (1 + rough * 4 * j) for j in jitter]
    raw = [0.6 * a + 0.4 * b for a, b in zip(saw(f, n), sine(fs, n))]
    return lowpass(drive(raw, 2.0), 400 + f * 3)


def whoosh(seconds: float, f0: float, f1: float, seed: int = 1, peak: float = 0.5) -> list[float]:
    """Filtered noise going by: jets, missiles, wind. It grows and brightens
    until ``peak`` (the moment it passes), then fades and darkens: the
    filter follows the loudness, from ``f0`` to ``f1`` and back down."""
    n = n_of(seconds)
    top = max(1, int(n * peak))
    env = [(i / top) ** 2 if i < top else ((n - i) / max(1, n - top)) ** 1.5 for i in range(n)]
    cut = [f0 * (f1 / f0) ** e for e in env]
    return mul(lowpass(white(n, seed), cut, 0.5), env)


def metal(n: int, f: float, seed: int = 1) -> list[float]:
    """A metallic clank: inharmonic partials, quickly gone."""
    rng = random.Random(seed)
    out = [0.0] * n
    for ratio in (1.0, 2.76, 5.4, 8.93):
        ph, step, amp = rng.random() * TAU, TAU * f * ratio * rng.uniform(0.98, 1.02) / RATE, 1 / ratio ** 0.5
        for i in range(n):
            out[i] += math.sin(ph) * amp
            ph += step
    return mul(out, decay(n, 0.04))


def siren(seconds: float, low: float = 420, high: float = 880, period: float = 2.4) -> list[float]:
    """An air-raid siren rising and falling."""
    n = n_of(seconds)
    fs = [low + (high - low) * (0.5 - 0.5 * math.cos(TAU * i / (period * RATE))) for i in range(n)]
    tone = [0.6 * a + 0.4 * b for a, b in zip(sine(fs, n), saw(fs[0], n))]
    return mul(lowpass(tone, 2500), adsr(n, 0.4, 0.1, 1.0, 0.8))


def loudness(x: list[float]) -> float:
    """The level of what actually sounds: the RMS of the 50 ms windows that
    are not near-silent (a gunshot is not quieter for its silence after)."""
    win = n_of(0.05)
    levels = [(sum(v * v for v in x[i:i + win]) / win) ** 0.5 for i in range(0, max(1, len(x) - win), win)]
    top = max(levels or [0.0])
    active = [v for v in levels if v > top * 0.25] or [top]
    return (sum(v * v for v in active) / len(active)) ** 0.5


def limit(v: float, knee: float = 0.8) -> float:
    """A soft limiter: untouched below the knee, rounded above, never past 1."""
    a = abs(v)
    if a <= knee:
        return v
    return math.copysign(knee + (1 - knee) * math.tanh((a - knee) / (1 - knee)), v)


# The mix: how far each sound sits from the common level, in dB. Steps,
# engines and the interface stay in the background; the bombs come forward.
MIX_DB = {"move_I": -6, "move_A": -4, "move_F": -3, "move_B": -4, "move_D": -5, "move_S": -4,
          "move_T": -5, "move_R": -4, "move_C": -4, "move_U": -6, "move_H": -3,
          "turn": -4, "card": -4, "spy": -5, "alert": -2, "truce": -3, "satellite": -2,
          "nuke": 2, "fall": 1, "fire_B": 1, "fire_H": 1}


def finish(out: dict[str, Track], level: float) -> dict[str, Track]:
    """The last touch on every sound: no DC offset (a 20 Hz high-pass), the
    same loudness for all (``level``: the RMS to reach, 1.0 = full scale),
    peaks rounded by a limiter, a few milliseconds of fade at both ends."""
    edge = n_of(0.004)
    for name, t in out.items():
        if getattr(t, "_finished", False):
            continue                    # the same track under two names
        buf = highpass(t.buf, 20)
        g = level * 10 ** (MIX_DB.get(name, 0) / 20) / max(1e-9, loudness(buf))
        buf = [limit(v * g) for v in buf]
        n = len(buf)
        for i in range(min(edge, n // 2)):
            k = i / edge
            buf[i] *= k
            buf[n - 1 - i] *= k
        t.buf = buf
        t._finished = True
        t.leveled = True                # pcm() must not normalise it again
    return out


def put(track: Track, at: float, samples: list[float], vol: float = 1.0) -> None:
    track.add(at, gain(samples, vol) if vol != 1.0 else samples)


# ------------------------------------------------------------------ effects
def unit_sounds() -> dict[str, Track]:
    out: dict[str, Track] = {}

    def make(seconds: float) -> Track:
        return Track(seconds)

    # Infantry: boots on gravel / a volley of rifles echoing in a valley.
    t = make(0.8)
    for k in range(3):
        step = mul(bandpass(white(n_of(0.09), 21 + k), 300, 2500), decay(n_of(0.09), 0.025))
        put(t, k * 0.21, step, 0.7)
    out["move_I"] = t
    t = make(1.6)
    shots = Track(0.9)
    for k, at in enumerate((0.0, 0.07, 0.16, 0.31, 0.38)):
        put(shots, at, gunshot(31 + k), 0.6)
    put(t, 0, reverb(shots.buf, 0.35, 1.4, tail=0.6))
    out["fire_I"] = t
    # Armour: a diesel growl and clanking tracks / the main gun.
    t = make(1.2)
    put(t, 0, mul(engine(38, 1.1, 0.25, 41), adsr(n_of(1.1), 0.1, 0.1, 1.0, 0.3)), 0.5)
    for k in range(7):
        put(t, 0.08 + k * 0.14, metal(n_of(0.06), 520 + 40 * (k % 3), 41 + k), 0.12)
    out["move_A"] = t
    t = make(2.0)
    put(t, 0, gunshot(51, 1.0), 0.8)
    put(t, 0.02, explosion(0.5, 52, distance=0.3), 0.7)
    out["fire_A"] = t
    # Fighter: a jet streaking past / a cannon burst.
    t = make(1.8)
    put(t, 0, whoosh(1.7, 300, 5000, 61, 0.55), 0.6)
    n = n_of(1.7)
    put(t, 0, mul(sine(glide(1800, 900, n), n), [0.05 * math.sin(math.pi * i / n) for i in range(n)]))
    out["move_F"] = t
    t = make(1.0)
    burst = Track(0.6)
    for k in range(10):
        put(burst, k * 0.045, gunshot(71 + k), 0.4)
    put(t, 0, reverb(burst.buf, 0.2, 0.8, tail=0.3))
    out["fire_F"] = t
    # Bomber: heavy engines throbbing / a stick of bombs walking in.
    t = make(1.8)
    a, b = engine(70, 1.7, 0.1, 81), engine(73.5, 1.7, 0.1, 82)
    put(t, 0, mul([x + y for x, y in zip(a, b)], adsr(n_of(1.7), 0.5, 0.1, 1.0, 0.6)), 0.3)
    out["move_B"] = t
    t = make(3.4)
    n = n_of(0.9)
    put(t, 0, mul(sine(glide(2200, 600, n), n), adsr(n, 0.05, 0.1, 0.8, 0.1)), 0.12)
    for k, at in enumerate((0.85, 1.15, 1.45)):
        put(t, at, explosion(0.8, 83 + k, distance=0.2 + 0.2 * k), 0.75 - 0.12 * k)
    out["fire_B"] = t
    # Destroyer: turbines and a bow wave / quick-firing guns.
    t = make(1.4)
    put(t, 0, whoosh(1.3, 200, 900, 91, 0.5), 0.5)
    put(t, 0, mul(engine(55, 1.3, 0.05, 92), adsr(n_of(1.3), 0.2, 0.1, 1.0, 0.4)), 0.25)
    out["move_D"] = t
    t = make(2.0)
    for k, at in enumerate((0.0, 0.28, 0.56)):
        put(t, at, gunshot(95 + k, 0.7), 0.6)
    put(t, 0.05, explosion(0.35, 98, distance=0.6), 0.4)
    out["fire_D"] = t
    # Submarine: a sonar ping in deep water / a torpedo and its hit.
    t = make(3.0)
    n = n_of(0.35)
    ping = mul(sine(glide(1250, 1180, n), n), decay(n, 0.12, 0.003))
    put(t, 0, reverb(ping, 0.6, 2.2, damp=0.2, tail=2.4), 0.6)
    out["move_S"] = t
    t = make(3.4)
    put(t, 0, lowpass(whoosh(1.2, 150, 700, 101, 0.7), 900), 0.5)
    put(t, 1.15, [v for v in lowpass(explosion(1.0, 103), 600)], 0.9)
    out["fire_S"] = t
    # Transport: a slow diesel and a horn across the harbour.
    t = make(2.4)
    put(t, 0, mul(engine(45, 2.2, 0.15, 111), adsr(n_of(2.2), 0.3, 0.1, 1.0, 0.6)), 0.3)
    n = n_of(1.0)
    horn = [a + b for a, b in zip(saw(110, n), saw(110 * 1.5, n, 0.4))]
    put(t, 0.3, reverb(mul(lowpass(horn, 700), adsr(n, 0.08, 0.1, 0.9, 0.25)), 0.4, 1.5, tail=1.0), 0.25)
    out["move_T"] = t
    out["fire_T"] = t
    # Cruiser: a deep horn / a broadside rolling over the sea.
    t = make(2.6)
    n = n_of(1.4)
    horn = [a + b + c for a, b, c in zip(saw(65.4, n), saw(98, n, 0.3), saw(65.4 * 1.005, n, 0.6))]
    put(t, 0, reverb(mul(lowpass(horn, 500), adsr(n, 0.1, 0.1, 0.9, 0.4)), 0.4, 1.6, tail=1.0), 0.3)
    out["move_R"] = t
    t = make(3.0)
    for k, at in enumerate((0.0, 0.22, 0.44)):
        put(t, at, gunshot(121 + k, 1.0), 0.6)
        put(t, at + 0.03, explosion(0.6, 124 + k, distance=0.5), 0.45)
    out["fire_R"] = t
    # Carrier: the deck horn, then a catapult launch / a strike group taking off.
    t = make(2.4)
    n = n_of(0.6)
    put(t, 0, mul(lowpass([a + b for a, b in zip(saw(73.4, n), saw(110, n))], 600), adsr(n, 0.05, 0.1, 0.9, 0.2)), 0.25)
    put(t, 0.6, whoosh(1.6, 400, 6000, 131, 0.35), 0.6)
    out["move_C"] = t
    t = make(2.6)
    for k in range(3):
        put(t, k * 0.35, whoosh(1.6, 300 + 100 * k, 5000, 141 + k, 0.4), 0.45)
    out["fire_C"] = t
    # Drone: the thin whine of propellers / a small missile, hiss and pop.
    t = make(1.2)
    n = n_of(1.1)
    whine = [a * (0.7 + 0.3 * math.sin(TAU * 23 * i / RATE)) for i, a in enumerate(saw(290, n))]
    put(t, 0, mul(lowpass(whine, 1800), adsr(n, 0.15, 0.1, 1.0, 0.4)), 0.15)
    out["move_U"] = t
    t = make(1.6)
    put(t, 0, whoosh(0.45, 2000, 6000, 161, 0.2), 0.4)
    put(t, 0.42, explosion(0.3, 162, distance=0.4), 0.5)
    out["fire_U"] = t
    # Hypersonic missile: a scream climbing out of hearing / the strike.
    t = make(1.6)
    n = n_of(1.4)
    put(t, 0, mul(sine(glide(300, 3500, n, 1.6), n), adsr(n, 0.05, 0.1, 1.0, 0.4)), 0.15)
    put(t, 0, whoosh(1.4, 500, 7000, 171, 0.6), 0.45)
    out["move_H"] = t
    t = make(2.6)
    n = n_of(0.15)
    put(t, 0, mul(sine(glide(4000, 600, n), n), decay(n, 0.05)), 0.25)
    put(t, 0.14, explosion(1.1, 172), 0.9)
    out["fire_H"] = t
    return out


def sfx() -> dict[str, Track]:
    out = unit_sounds()
    t = Track(1.2)    # a card dealt on the table, then a soft synth sting
    put(t, 0, mul(bandpass(white(n_of(0.05), 151), 800, 6000), decay(n_of(0.05), 0.012)), 0.6)
    for k, name in enumerate(("E5", "A5", "C#6")):
        put(t, 0.08 + 0.07 * k, pluck(freq(name), 0.6, 0.25))
    out["card"] = Track(1.8)
    put(out["card"], 0, reverb(t.buf, 0.3, 1.0, tail=0.6))
    t = Track(4.0)    # a launch: the rocket's roar, then telemetry beeps from orbit
    put(t, 0, mul(lowpass(white(n_of(2.4), 181), glide(200, 1800, n_of(2.4))), adsr(n_of(2.4), 0.6, 0.2, 0.9, 1.0)), 0.7)
    put(t, 0, mul(engine(30, 2.4, 0.3, 182), adsr(n_of(2.4), 0.6, 0.2, 0.9, 1.0)), 0.35)
    beeps = Track(1.4)
    for k in range(4):
        put(beeps, k * 0.25, mul(sine(1760 if k % 2 else 2093, n_of(0.07)), adsr(n_of(0.07), 0.003, 0.02, 0.8, 0.02)), 0.2)
    put(t, 2.3, reverb(beeps.buf, 0.4, 1.2, tail=0.4))
    out["satellite"] = t
    t = Track(2.0)    # the ASAT: a charging whine, the zap, static
    n = n_of(0.5)
    put(t, 0, mul(sine(glide(300, 2400, n, 2.0), n), adsr(n, 0.4, 0.05, 1.0, 0.02)), 0.15)
    n = n_of(0.3)
    put(t, 0.5, mul([a + 0.5 * b for a, b in zip(saw(2600, n), white(n, 191))], decay(n, 0.08)), 0.3)
    put(t, 0.8, mul(bandpass(white(n_of(0.9), 192), 1500, 7000), adsr(n_of(0.9), 0.01, 0.1, 0.4, 0.5)), 0.25)
    out["asat"] = t
    t = Track(1.6)    # the spies: a burst of data on an encrypted line
    rng = random.Random(7)
    for k in range(14):
        f = rng.choice((1200, 1600, 2400, 3200))
        put(t, k * 0.075, mul(sine(f, n_of(0.05)), adsr(n_of(0.05), 0.002, 0.01, 0.8, 0.01)), 0.12)
    out["spy"] = t
    t = Track(2.6)    # a battle: guns and a hit
    put(t, 0, gunshot(3, 0.8), 0.6)
    put(t, 0.15, explosion(0.7, 4), 0.8)
    put(t, 0.5, gunshot(5, 0.4), 0.3)
    out["battle"] = t
    t = Track(2.6)    # a city taken: a brass swell and a drum hit
    for name in ("C4", "G4", "C5", "E5"):
        put(t, 0, brass(freq(name), 1.6), 0.5)
    put(t, 0, taiko(0.7, 80))
    put(t, 0, crash(0.18))
    out["capture"] = Track(3.6)
    put(out["capture"], 0, reverb(t.buf, 0.3, 1.3, tail=1.0))
    t = Track(2.6)    # something of ours lost: a low cluster and a boom
    for name in ("A2", "C3", "D#3"):
        put(t, 0, strings(freq(name), 2.0, 0.3))
    put(t, 0, taiko(0.6, 55))
    out["loss"] = Track(3.6)
    put(out["loss"], 0, reverb(t.buf, 0.35, 1.4, tail=1.0))
    t = Track(4.0)    # a whole faction falls: the "braam" of modern trailers
    for name in ("D1", "D2", "A2", "D3", "F3"):
        put(t, 0, brass(freq(name), 3.0), 0.7)
    put(t, 0, taiko(0.9, 50))
    put(t, 0, explosion(0.8, 21, distance=0.6), 0.4)
    out["fall"] = Track(5.0)
    put(out["fall"], 0, reverb(drive(t.buf, 1.3), 0.3, 1.5, tail=1.0))
    t = Track(9.0)    # nuclear strike: the siren, the whistle, the flash, the blast
    put(t, 0, reverb(siren(3.2), 0.35, 1.8, tail=0.8), 0.35)
    n = n_of(1.2)
    put(t, 3.0, mul(sine(glide(2400, 350, n), n), adsr(n, 0.1, 0.1, 0.9, 0.1)), 0.12)
    put(t, 4.2, mul(highpass(white(n_of(0.05), 8), 1000), decay(n_of(0.05), 0.02)), 0.9)
    put(t, 4.2, explosion(2.8, 7), 1.0)
    put(t, 4.6, mul(lowpass(white(n_of(4.0), 9), 200), adsr(n_of(4.0), 0.3, 0.5, 0.6, 2.5)), 0.6)
    out["nuke"] = t
    t = Track(2.4)    # a missile shot down: the interceptor climbs, the burst high up
    n = n_of(0.8)
    put(t, 0, whoosh(0.8, 600, 6000, 10, 0.8), 0.4)
    put(t, 0.8, highpass(explosion(0.6, 11, distance=0.6), 300), 0.6)
    out["intercept"] = t
    t = Track(2.6)    # gas: a long hiss, slowly spreading
    n = n_of(2.0)
    put(t, 0, mul(lowpass(highpass(white(n, 13), 700), glide(7000, 1500, n)), adsr(n, 0.15, 0.2, 0.7, 1.2)), 0.6)
    put(t, 0, mul(sine(glide(70, 55, n), n), adsr(n, 0.4, 0.2, 0.6, 1.0)), 0.25)
    out["gas"] = t
    t = Track(2.6)    # an aircraft down: the dive and the impact
    n = n_of(1.1)
    put(t, 0, mul(sine(glide(1600, 250, n), n), adsr(n, 0.05, 0.1, 0.9, 0.05)), 0.15)
    put(t, 0, whoosh(1.1, 3000, 400, 16, 0.8), 0.4)
    put(t, 1.05, explosion(0.6, 17), 0.8)
    out["crash"] = t
    t = Track(3.2)    # a truce: a warm, open chord
    for name in ("D4", "A4", "E5", "F#5"):
        put(t, 0, strings(freq(name), 2.4, 0.22))
    out["truce"] = Track(4.0)
    put(out["truce"], 0, reverb(t.buf, 0.4, 1.4, tail=0.8))
    t = Track(1.6)    # your turn: a crisp two-note chime
    put(t, 0, epiano(freq("E6"), 0.9, 0.35))
    put(t, 0.12, epiano(freq("B6"), 1.0, 0.3))
    out["turn"] = Track(2.4)
    put(out["turn"], 0, reverb(t.buf, 0.35, 1.2, tail=0.6))
    t = Track(1.6)    # a modern alarm: a filtered pulsing tone
    for k in range(3):
        n = n_of(0.22)
        tone = [a + b for a, b in zip(saw(660, n), saw(990, n, 0.3))]
        put(t, k * 0.3, mul(lowpass(tone, 2200, 0.4), adsr(n, 0.005, 0.05, 0.8, 0.05)), 0.25)
    out["alert"] = Track(2.2)
    put(out["alert"], 0, reverb(t.buf, 0.25, 1.0, tail=0.5))
    return finish(out, 0.22)


# -------------------------------------------------------------------- music
def notes_down(notes, octaves: int = 1):
    return [(n if n == "R" else n[:-1] + str(int(n[-1]) - octaves), b) for n, b in notes]


def play(track: Track, notes, tempo, voice, start: float = 0.0, length: float = 0.95, **kw) -> float:
    """Like audio.sequence, for the modern voices."""
    tempo = tempo if isinstance(tempo, list) else [(0, tempo)]
    b = 0.0
    for name, beats in notes:
        t0, t1 = beat_time(tempo, b), beat_time(tempo, b + beats)
        if name != "R":
            track.add(start + t0, voice(freq(name), (t1 - t0) * length, **kw))
        b += beats
    return start + beat_time(tempo, b)


def music() -> dict[str, Track]:
    out: dict[str, Track] = {}
    # Menu: the Toccata's motif on low brass, over a dark pad, a sub pulse
    # and slow ticks; a cold-war briefing room rather than an organ.
    bpm = 70
    beats = sum(b for _, b in MENU_LEAD)
    seconds = beats * 60 / bpm + 1.0
    t = Track(seconds)
    beat = 60 / bpm
    for k, (root, notes) in enumerate((("D2", ("D3", "A3", "F4")), ("Bb1", ("Bb2", "F3", "D4")),
                                       ("G1", ("G2", "D3", "Bb3")), ("A1", ("A2", "E3", "C#4")))):
        at = k * seconds / 4
        chord(t, at, list(notes), seconds / 4 + 0.6, strings, 0.12)
        put(t, at, bass(freq(root), seconds / 4, 0.25))
    play(t, MENU_LEAD, bpm, brass, vol=0.45)
    play(t, notes_down(MENU_LEAD), bpm, brass, vol=0.25)
    for k in range(int(seconds / beat)):
        put(t, k * beat, hat(0.06 if k % 2 else 0.1, seed=k))
    out["menu"] = Track(seconds)
    put(out["menu"], 0, reverb(t.buf, 0.35, 1.5, tail=0)[: len(t.buf)])
    # War: hybrid orchestral at 116 bpm. Eight bars build (pumping bass
    # ostinato, taiko and snare, string chords), then the march's theme on
    # brass over the same, with the bass and the strings ducking at the kick.
    bpm = 116
    beat = 60 / bpm
    bars = len(WAR_CHORDS)
    seconds = bars * 2 * 4 * beat
    t = Track(seconds + 0.5)
    chord_notes = {"D": ("D3", "F3", "A3"), "Bb": ("D3", "F3", "Bb3"), "A": ("C#3", "E3", "A3"),
                   "F": ("C3", "F3", "A3"), "G": ("D3", "G3", "Bb3")}
    bed = Track(seconds + 0.5)
    for rep in range(2):
        for k, name in enumerate(WAR_CHORDS):
            at = (rep * bars + k) * 4 * beat
            chord(bed, at, list(chord_notes[name]), 4 * beat, strings, 0.11 if rep else 0.08)
            root = WAR_BASS_BAR[name][0][0]
            for e in range(8):                       # eighth-note ostinato
                note = root if e % 4 != 3 else WAR_BASS_BAR[name][1][0]
                bed.add(at + e * beat / 2, bass(freq(note), beat / 2 * 0.9, 0.3))
    put(t, 0, pump(bed.buf, beat, 0.0, 0.55))
    for b in range(bars * 2 * 4):
        at = b * beat
        if b % 4 in (0, 2):
            put(t, at, kick(0.75))
        if b % 4 in (1, 3):
            put(t, at, snare(0.4, seed=b))
        put(t, at + beat / 2, hat(0.08, seed=b))
        if b % 8 == 0:
            put(t, at, taiko(0.55, 70))
        if b % 16 == 14:                             # a roll into the next phrase
            for r in range(4):
                put(t, at + beat + r * beat / 4, snare(0.15 + 0.06 * r, seed=200 + r))
    play(t, WAR_MELODY, bpm, brass, start=bars * 4 * beat, vol=0.55)
    play(t, WAR_MELODY, bpm, lead, start=bars * 4 * beat, vol=0.12, bright=1800)
    put(t, bars * 4 * beat, crash(0.2))
    out["war"] = Track(seconds)
    put(out["war"], 0, reverb(t.buf, 0.22, 1.2, tail=0)[: int(seconds * RATE)])
    # Tension: a heartbeat in the sub, a clock ticking, a drone that opens
    # and closes, strings trembling on a dissonance.
    seconds = 16.0
    t = Track(seconds)
    n = n_of(seconds)
    drone = [a + b for a, b in zip(saw(36.7, n), saw(36.7 * 1.5 * 1.003, n, 0.2))]
    sweep = [300 + 500 * (0.5 - 0.5 * math.cos(TAU * i / n)) for i in range(n)]
    put(t, 0, mul(lowpass(drone, sweep, 0.5), adsr(n, 1.5, 0.1, 1.0, 1.5)), 0.22)
    for name in ("A4", "Bb4", "E5"):
        f = freq(name)
        put(t, 0, mul(strings(f, seconds, 0.05), [0.6 + 0.4 * math.sin(TAU * 7 * i / RATE) for i in range(n)]))
    for k in range(int(seconds)):
        put(t, k, mul(sine(glide(65, 40, n_of(0.18)), n_of(0.18)), decay(n_of(0.18), 0.06)), 0.8)
        put(t, k + 0.24, mul(sine(glide(55, 38, n_of(0.15)), n_of(0.15)), decay(n_of(0.15), 0.05)), 0.55)
    for k in range(int(seconds * 2)):
        put(t, k * 0.5, metal(n_of(0.03), 2400 if k % 2 else 1900, k), 0.05)
    out["tension"] = Track(seconds)
    put(out["tension"], 0, reverb(t.buf, 0.35, 1.6, tail=0)[: n])
    # Victory: the fanfare on brass over a swelling major chord, timpani and cymbal.
    bpm = 132
    t = Track(8.0)
    fanfare = [("G4", 0.5), ("C5", 0.5), ("E5", 0.5), ("G5", 1.5), ("E5", 0.5), ("G5", 3),
               ("A5", 0.5), ("G5", 0.5), ("F5", 0.5), ("E5", 0.5), ("D5", 0.5), ("C5", 3)]
    play(t, fanfare, bpm, brass, vol=0.6)
    play(t, fanfare, bpm, lead, vol=0.12, bright=2200)
    chord(t, 0, ["C3", "G3", "C4", "E4"], 3.6, strings, 0.14)
    chord(t, 3.6, ["F3", "A3", "C4", "F4"], 1.6, strings, 0.14)
    chord(t, 5.2, ["C3", "G3", "C4", "E4"], 2.6, strings, 0.16)
    for k in range(6):
        put(t, k * 0.11, timpani(98, 0.25 + 0.06 * k))
    put(t, 5.2, timpani(65.4, 0.8))
    put(t, 5.2, crash(0.3))
    out["victory"] = Track(9.0)
    put(out["victory"], 0, reverb(t.buf, 0.3, 1.5, tail=1.0))
    # Defeat: the lament on an electric piano, over a low pad, in a big room.
    bpm = 60
    t = Track(9.0)
    play(t, [("A4", 1), ("G4", 1), ("F4", 1), ("E4", 2), ("D4", 3)], bpm, epiano, length=1.4, vol=0.4)
    chord(t, 0, ["D3", "F3", "A3"], 4.0, strings, 0.1)
    chord(t, 4.0, ["A2", "E3", "C#4"], 4.5, strings, 0.1)
    out["defeat"] = Track(11.0)
    put(out["defeat"], 0, reverb(t.buf, 0.45, 1.8, tail=2.0))
    # Midnight: wind over a dead world, a drone, a Geiger counter.
    seconds = 11.0
    t = Track(seconds)
    n = n_of(seconds)
    wind_cut = [250 + 400 * (0.5 + 0.5 * math.sin(TAU * i / (3.7 * RATE)) * math.sin(TAU * i / (5.3 * RATE)))
                for i in range(n)]
    put(t, 0, mul(lowpass(white(n, 99), wind_cut, 0.6), adsr(n, 2.5, 0.1, 1.0, 3.0)), 0.9)
    put(t, 0, mul(lowpass(saw(32.7, n), 120), adsr(n, 2.0, 0.1, 1.0, 3.0)), 0.3)
    rng = random.Random(5)
    for _ in range(40):
        at = rng.uniform(0.5, seconds - 0.5)
        put(t, at, mul(highpass(white(n_of(0.004), rng.randrange(999)), 2000), decay(n_of(0.004), 0.001)), 0.25)
    out["midnight"] = Track(seconds)
    put(out["midnight"], 0, reverb(t.buf, 0.4, 2.0, tail=0)[: n])
    # Kalinka: the dance on a bright pluck doubled an octave up, a synth
    # bass, kick and claps on the refrain; the verse on brass, broad.
    tempo = KALINKA_TEMPO
    beats = sum(b for _, b in KALINKA_BASS)
    seconds = beat_time(tempo, beats) + 0.3
    t = Track(seconds)
    end = play(t, KALINKA_REFRAIN, tempo, pluck, vol=0.4)
    play(t, KALINKA_REFRAIN, tempo, pluck, vol=0.12, length=0.8)
    play(t, [(n[:-1] + str(int(n[-1]) + 1) if n != "R" else n, b) for n, b in KALINKA_REFRAIN], tempo, pluck,
         vol=0.1)
    refrain_beats = sum(b for _, b in KALINKA_REFRAIN)
    verse_start = beat_time(tempo, refrain_beats)
    verse = Track(seconds)
    play(verse, KALINKA_VERSE, [(b0 - refrain_beats, bpm) for b0, bpm in tempo], brass, start=verse_start,
         vol=0.5)
    put(t, 0, verse.buf)
    play(t, KALINKA_BASS, tempo, bass, vol=0.35, length=0.85)
    step = 60.0 / 174
    first = beat_time(tempo, 1)
    for b in range(int((end - first) / step)):
        at = first + b * step
        put(t, at, kick(0.6) if b % 2 == 0 else snare(0.3, seed=b))
        put(t, at + step / 2, hat(0.07, seed=b))
    out["kalinka"] = Track(seconds)
    put(out["kalinka"], 0, reverb(t.buf, 0.18, 1.0, tail=0)[: len(t.buf)])
    # The anthem: brass and strings in a hall, timpani on the strong beats.
    bpm = 76
    beats = sum(b for _, b in ANTHEM_MELODY)
    seconds = beats * 60 / bpm + 0.5
    t = Track(seconds)
    play(t, ANTHEM_MELODY, bpm, brass, vol=0.55)
    play(t, ANTHEM_MELODY, bpm, strings, vol=0.08, length=1.0)
    at = 0.5 * 60 / bpm
    for root in ANTHEM_CHORDS:
        low = "1" if root in "AB" else "2"
        top = ANTHEM_FIFTH[root] + ("2" if root in "FGAB" else low)
        put(t, at, bass(freq(root + low), 60 / bpm * 0.95, 0.28))
        put(t, at + 60 / bpm, bass(freq(top), 60 / bpm * 0.95, 0.22))
        chord(t, at, [root + "3", ANTHEM_FIFTH[root] + "3"], 2 * 60 / bpm, strings, 0.06)
        put(t, at, timpani(freq(root + "2"), 0.3))
        at += 2 * 60 / bpm
    out["anthem"] = Track(seconds)
    put(out["anthem"], 0, reverb(t.buf, 0.3, 1.6, tail=0)[: len(t.buf)])
    return finish(out, 0.11)        # the music sits under the effects
