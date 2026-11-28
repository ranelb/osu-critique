"""Spinner rating: by spin completion, never by press timing.

The game does not time a spinner like a circle. It asks how far the cursor
turned around the playfield centre while the spinner was up, and compares that
with the rotations the spinner demands:

    required = int(seconds * DifficultyRange(OD, 1.5, 2.5, 3.75))
    progress = rotations / required
    >= 1 -> 300, > 0.9 -> 100, > 0.75 -> 50, else miss

(osu!lazer ``OsuSpinner`` / ``DrawableSpinner``; ``seconds`` is **map** time, so
a DT play must turn faster in real time, not further.) ``judge`` used to push a
spinner through the circle OD window, which turned the first press inside the
spin into a "timing error" of hundreds of ms and rated about half of all
spinners 50 or miss.

What is approximate: rotations are the sum of the absolute per-frame angle
change of the *recorded* cursor, with no per-frame rate cap and no check that a
key is held. Both variants were measured against the recorded counts and moved
nothing (see docs/ROADMAP.md "Spinner rating"), so the simplest rule stays. The
model cannot tell a spinner the game rated 100 from one it rated 300 unless the
cursor actually fell short, and it has no per-spinner ground truth.
"""
from __future__ import annotations

import bisect
import math

CENTER = (256.0, 192.0)


def _difficulty_range(od, minimum, mid, maximum):
    if od > 5:
        return mid + (maximum - mid) * (od - 5) / 5
    if od < 5:
        return mid - (mid - minimum) * (5 - od) / 5
    return mid


def spins_required(od, duration_ms):
    """Whole rotations the game asks for (``duration_ms`` in map time)."""
    return int(duration_ms / 1000.0 * _difficulty_range(od, 1.5, 2.5, 3.75))


def rotations(frames, times, t0, t1):
    """Rotations of the recorded cursor around the centre inside [t0, t1].

    ``times`` is the sorted frame-time sequence (list or array) that matches
    ``frames``; frames are ``(t, x, y, ...)``.
    """
    lo = bisect.bisect_left(times, t0)
    hi = bisect.bisect_right(times, t1)
    total = 0.0
    prev = None
    for k in range(lo, hi):
        ang = math.atan2(frames[k][2] - CENTER[1], frames[k][1] - CENTER[0])
        if prev is not None:
            d = (ang - prev + math.pi) % (2 * math.pi) - math.pi
            total += abs(d)
        prev = ang
    return total / (2 * math.pi)


def rate(progress):
    """Result for a completion ratio."""
    if progress >= 1.0:
        return "300"
    if progress > 0.9:
        return "100"
    if progress > 0.75:
        return "50"
    return "miss"


def judge_spinner(frames, times, o, od, scale):
    """(result, progress, required) for spinner row ``o``.

    ``o["t"]``/``o["end"]`` are in the frames' clock; ``scale`` converts that
    clock back to map time (frames clock = map time * scale).
    """
    duration_map = (o["end"] - o["t"]) / (scale or 1.0)
    required = spins_required(od, duration_map)
    if required <= 0:
        return "300", 1.0, 0
    progress = rotations(frames, times, o["t"], o["end"]) / required
    return rate(progress), progress, required
