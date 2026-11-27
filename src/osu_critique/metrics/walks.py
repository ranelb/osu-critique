"""Polygons and stars by walking the turns, so one lap is enough.

``geometry`` finds a polygon by looking for a figure repeated twice (a cycle). That
rightly refuses most short windows, but a pentagon or a five-point star is *also* a walk
of equal legs with an equal turn at every vertex: 72 degrees for a pentagon, 144 for a
{5/2} star, 120 a triangle, 90 a square, 60 a hexagon. Four such legs are enough to
name it, no second lap needed.

    find(objs, radius, beat_at=None) -> segments  (same keys as ``geometry`` + ``turn_deg``, ``ideal_deg``)

A walk is >= ``MIN_TURNS`` consecutive turns that all have the same sign and sit within
``min(TOL_MAX, TOL_FRAC * ideal)`` degrees of one ideal angle in ``IDEALS``, with legs of
similar length (within ``LEG_RATIO`` of their median, all >= ``MIN_LEG_R`` radii so the
heading means something) and steady timing. The ideal is the nearest table entry; the
shape comes from it. Alternating-sign turns (zigzag) never qualify. Legs and turns follow
``legs.py`` / ``geometry``: exit-to-head, positive = clockwise on screen, spinners break.
"""
from __future__ import annotations

import math
import statistics as st

# ideal exterior turn (degrees) -> shape. A star {5/2} turns 144, a triangle 120.
IDEALS = {60.0: "hexagon", 72.0: "pentagon", 90.0: "square", 120.0: "triangle", 144.0: "star"}
TABLE = {
    "min_turns": 3,
    "min_leg_r": 2.0,       # polygon legs are jumps; shorter legs are streams (see curves.py)
    "tol_max": 22.0,
    "tol_frac": 0.2,
    "leg_ratio": 1.35,      # each leg within this factor of the run's median leg
    "gap_ratio": 1.35,
    "max_beats": 4.0,
}


def _end(o):
    return o.get("end_x", o["x"]), o.get("end_y", o["y"])


def _wrap(d):
    return (d + 180.0) % 360.0 - 180.0


def _tol(ideal):
    return min(TABLE["tol_max"], TABLE["tol_frac"] * ideal)


def _sides(ideal):
    return 5 if ideal == 144.0 else round(360.0 / ideal)


def _distinct(objs, a, b, ideal, radius):
    """Vertices may only coincide one full lap apart; otherwise it is a repeated stack, not a polygon."""
    k = _sides(ideal)
    for p in range(a, b + 1):
        for q in range(p + 2, b + 1):
            if (q - p) % k == 0:
                continue
            (x0, y0), (x1, y1) = _end(objs[p]), (objs[q]["x"], objs[q]["y"])
            if math.hypot(x1 - x0, y1 - y0) < radius:
                return False
    return True


def find(objs, radius, beat_at=None):
    t = TABLE
    n = len(objs)
    ang = [None] * n
    ln = [None] * n
    for i in range(1, n):
        a, b = objs[i - 1], objs[i]
        if a["kind"] == "Spinner" or b["kind"] == "Spinner":
            continue
        ex, ey = _end(a)
        dx, dy = b["x"] - ex, b["y"] - ey
        r = math.hypot(dx, dy) / radius
        if r >= t["min_leg_r"]:
            ang[i], ln[i] = math.degrees(math.atan2(dy, dx)), r
    turn = [None] * n
    for i in range(2, n):
        if ang[i] is not None and ang[i - 1] is not None:
            turn[i] = _wrap(ang[i] - ang[i - 1])

    def ideal_of(tv):
        return min(IDEALS, key=lambda k: abs(abs(tv) - k)) if tv is not None else None

    out, i = [], 2
    while i < n:
        if turn[i] is None:
            i += 1
            continue
        ideal = ideal_of(turn[i])
        sign = 1 if turn[i] > 0 else -1
        best = None
        for ideal in IDEALS:
            tol = _tol(ideal)
            j = i
            while (j + 1 < n and turn[j + 1] is not None and turn[j + 1] * sign > 0
                   and abs(abs(turn[j + 1]) - ideal) <= tol):
                j += 1
            if abs(abs(turn[i]) - ideal) > tol:
                continue
            err = abs(abs(turn[i]) - ideal)
            if best is None or j > best[0] or (j == best[0] and err < best[2]):
                best = (j, ideal, err)
        if best is None or best[0] - i + 1 < t["min_turns"]:
            i += 1
            continue
        j, ideal, _err = best
        ok = False
        while j - i + 1 >= t["min_turns"]:     # trim from the right until legs and timing are steady
            a, b = i - 2, j
            legs = [ln[x] for x in range(a + 1, b + 1)]
            gaps = [objs[x]["t"] - objs[x - 1]["t"] for x in range(a + 1, b + 1)]
            ml, mg = st.median(legs), st.median(gaps)
            ok = all(1 / t["leg_ratio"] <= x / ml <= t["leg_ratio"] for x in legs) and \
                all(1 / t["gap_ratio"] <= g / mg <= t["gap_ratio"] for g in gaps)
            if ok and not _distinct(objs, a, b, ideal, radius):
                ok = False
            if ok and beat_at is not None and \
                    objs[b]["t"] - objs[a]["t"] > t["max_beats"] * beat_at(objs[a]["t"]):
                ok = False
            if ok:
                break
            j -= 1
        if ok:
            tv = [abs(turn[x]) for x in range(i, j + 1)]
            out.append({
                "shape": IDEALS[ideal], "start": a, "end": b, "n": b - a + 1,
                "t0": objs[a]["t"], "t1": objs[b]["t"], "rate_ms": mg, "spacing_r": ml,
                "has_sliders": any(o["kind"] == "Slider" for o in objs[a:b + 1]),
                "dir": "cw" if sign > 0 else "ccw",
                "turn_deg": round(st.mean(tv), 1), "ideal_deg": ideal,
                "turn_sd": round(st.pstdev(tv), 1),
            })
            i = j + 1
        else:
            i += 1
    return out
