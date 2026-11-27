"""Smooth dense paths: the shapes ``geometry`` cannot see because they have no corners.

A curvy stream (a 1/4 or 1/2 stream whose notes follow a bending path, a ring of
touching notes, a long arc) is a run of notes ~1-3 circle radii apart with no repeating
figure, so the cycle detectors in ``geometry`` rightly say nothing. What defines it is
the *path*: the notes advance along a smooth curve at stream speed. Legs that short
carry no usable heading (ROADMAP: under ~1.5 r a direction is noise), so smoothness is
judged on **chords** two legs long, never on single legs.

    find(objs, radius, beat_at=None) -> segments   same keys as ``geometry`` plus ``form`` and ``sweep_deg``

A run qualifies when, over >= ``MIN_N`` objects and no spinner:
  * every leg is ``DENSE_MIN_R``..``DENSE_MAX_R`` radii and <= ``STREAM_MAX_GAP`` ms;
  * the path keeps moving: object i and i+4 are >= ``ADVANCE_R`` apart (a four-note
    square loop or a stack fails this, a ring of 10+ does not);
  * consecutive chords turn by <= ``CHORD_TURN_MAX`` degrees (a corner ends the run).
Shape: ``line`` if the run never leaves its end-to-end chord by more than ``LINE_DEV_R``;
``circle`` if a circle fit covers >= ``CIRCLE_SWEEP`` degrees; otherwise ``curvy_stream``,
with ``form`` = ``arc`` (single circle fit within ``ARC_RESID_R``) or ``s_curve``.
A path that bends one way then the other is cut at the inflection, and a piece never
spans more than ``max_beats`` of the local tempo (pass ``beat_at``). All thresholds are in ``TABLE``. Deterministic, local, no model.
"""
from __future__ import annotations

import math
import statistics as st

from .rhythm import STREAM_MAX_GAP

TABLE = {
    "min_n": 6,
    "dense_min_r": 0.5,
    "dense_max_r": 3.5,
    "advance_r": 1.0,
    "chord_turn_max": 100.0,
    "line_dev_r": 0.5,
    "circle_sweep": 300.0,
    "arc_resid_r": 0.4,
    "leg_turn_max": 65.0,    # one corner sharper than this ends the run (a curve spreads its turning)
    "bend_dead_deg": 12.0,   # a flip of curvature needs this much turn the other way
    "max_beats": 4.0,        # a pattern is at most one measure; longer runs are chunked
}


def _end(o):
    return o.get("end_x", o["x"]), o.get("end_y", o["y"])


def _wrap(d):
    return (d + 180.0) % 360.0 - 180.0


def _dense_legs(objs, radius):
    """ok[i] True when the leg (i-1 -> i) is dense and fast."""
    t = TABLE
    ok = [False] * len(objs)
    for i in range(1, len(objs)):
        a, b = objs[i - 1], objs[i]
        if a["kind"] == "Spinner" or b["kind"] == "Spinner":
            continue
        ex, ey = _end(a)
        r = math.hypot(b["x"] - ex, b["y"] - ey) / radius
        ok[i] = t["dense_min_r"] <= r <= t["dense_max_r"] and b["t"] - a["t"] <= STREAM_MAX_GAP
    return ok


def _split(objs, lo, hi, radius):
    """Cut [lo, hi] into smooth, advancing pieces; yield (start, end) with >= min_n objects."""
    t = TABLE
    P = [(o["x"], o["y"]) for o in objs]
    cuts = set()
    for i in range(lo, hi - 3):
        if math.dist(P[i], P[i + 4] if i + 4 <= hi else P[hi]) / radius < t["advance_r"] and i + 4 <= hi:
            cuts.add(i + 2)
    for i in range(lo + 1, hi):
        a = (P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1])
        b = (P[i + 1][0] - P[i][0], P[i + 1][1] - P[i][1])
        if min(math.hypot(*a), math.hypot(*b)) / radius >= 1.0:
            turn = _wrap(math.degrees(math.atan2(b[1], b[0]) - math.atan2(a[1], a[0])))
            if abs(turn) > t["leg_turn_max"]:
                cuts.add(i)
    for i in range(lo + 2, hi - 1):
        a = (P[i][0] - P[i - 2][0], P[i][1] - P[i - 2][1])
        b = (P[i + 2][0] - P[i][0], P[i + 2][1] - P[i][1]) if i + 2 <= hi else None
        if b is None or not (a[0] or a[1]) or not (b[0] or b[1]):
            continue
        turn = _wrap(math.degrees(math.atan2(b[1], b[0]) - math.atan2(a[1], a[0])))
        if abs(turn) > t["chord_turn_max"]:
            cuts.add(i)
    # inflections: the path stops bending one way and starts bending the other
    sign, acc = 0, 0.0
    for i in range(lo + 2, hi - 1):
        if i + 2 > hi:
            break
        a = (P[i][0] - P[i - 2][0], P[i][1] - P[i - 2][1])
        b = (P[i + 2][0] - P[i][0], P[i + 2][1] - P[i][1])
        if not (a[0] or a[1]) or not (b[0] or b[1]):
            continue
        turn = _wrap(math.degrees(math.atan2(b[1], b[0]) - math.atan2(a[1], a[0])))
        if sign == 0:
            sign = 1 if turn >= 0 else -1
        elif turn * sign < 0:
            acc += abs(turn)
            if acc >= t["bend_dead_deg"]:
                cuts.add(i)
                sign, acc = -sign, 0.0
        else:
            acc = 0.0
    start = lo
    for c in sorted(cuts) + [hi + 1]:
        end = c - 1 if c <= hi else hi
        if end - start + 1 >= t["min_n"]:
            yield start, end
        start = c


def _fit_circle(pts):
    """Kasa least squares: (cx, cy, r, rms residual)."""
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    suu = suv = svv = suuu = svvv = suvv = svuu = 0.0
    for x, y in pts:
        u, v = x - mx, y - my
        suu += u * u; suv += u * v; svv += v * v
        suuu += u ** 3; svvv += v ** 3; suvv += u * v * v; svuu += v * u * u
    det = suu * svv - suv * suv
    if abs(det) < 1e-9:
        return None
    a = 0.5 * (suuu + suvv)
    b = 0.5 * (svvv + svuu)
    uc = (a * svv - b * suv) / det
    vc = (b * suu - a * suv) / det
    cx, cy = mx + uc, my + vc
    r = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    rms = math.sqrt(sum((math.hypot(x - cx, y - cy) - r) ** 2 for x, y in pts) / n)
    return cx, cy, r, rms


def _sweep(pts, cx, cy):
    ang = [math.degrees(math.atan2(y - cy, x - cx)) for x, y in pts]
    tot = sum(_wrap(b - a) for a, b in zip(ang, ang[1:]))
    return abs(tot)


def _line_dev(pts):
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    L = math.hypot(x1 - x0, y1 - y0)
    if L < 1e-9:
        return float("inf")
    return max(abs((x1 - x0) * (y0 - y) - (x0 - x) * (y1 - y0)) / L for x, y in pts)


def _classify(pts, radius):
    t = TABLE
    if _line_dev(pts) / radius <= t["line_dev_r"]:
        return "line", "straight", 0.0, 0.0
    fit = _fit_circle(pts)
    if fit is None:
        return "line", "straight", 0.0, 0.0
    cx, cy, r, rms = fit
    # n points span n-1 steps; a closed ring of n notes is n steps around, so add the last one
    sweep = _sweep(pts, cx, cy) * len(pts) / max(1, len(pts) - 1)
    resid = rms / radius
    if sweep >= t["circle_sweep"] and resid <= t["arc_resid_r"]:
        return "circle", "circle", sweep, resid
    return "curvy_stream", ("arc" if resid <= t["arc_resid_r"] else "s_curve"), sweep, resid


def _chunks(objs, a, b, beat_at):
    """Split [a, b] so no piece spans more than ``max_beats`` of the local tempo."""
    if beat_at is None:
        yield a, b
        return
    cap = TABLE["max_beats"] * beat_at(objs[a]["t"])
    start = a
    for k in range(a, b + 1):
        if objs[k]["t"] - objs[start]["t"] > cap:
            if k - 1 - start + 1 >= TABLE["min_n"]:
                yield start, k - 1
            start = k
    if b - start + 1 >= TABLE["min_n"]:
        yield start, b


def find(objs, radius, beat_at=None):
    ok = _dense_legs(objs, radius)
    out, i, n = [], 1, len(objs)
    while i < n:
        if not ok[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and ok[j + 1]:
            j += 1
        lo, hi = i - 1, j          # objects lo..hi; leg lo+1..hi are the dense ones
        pieces = [c for a0, b0 in _split(objs, lo, hi, radius) for c in _chunks(objs, a0, b0, beat_at)]
        for a, b in pieces:
            pts = [(o["x"], o["y"]) for o in objs[a:b + 1]]
            shape, form, sweep, resid = _classify(pts, radius)
            gaps = [objs[k]["t"] - objs[k - 1]["t"] for k in range(a + 1, b + 1)]
            out.append({
                "shape": shape, "form": form, "start": a, "end": b, "n": b - a + 1,
                "t0": objs[a]["t"], "t1": objs[b]["t"], "rate_ms": st.median(gaps),
                "spacing_r": st.median(
                    math.hypot(objs[k]["x"] - _end(objs[k - 1])[0],
                               objs[k]["y"] - _end(objs[k - 1])[1]) / radius
                    for k in range(a + 1, b + 1)),
                "has_sliders": any(o["kind"] == "Slider" for o in objs[a:b + 1]),
                "sweep_deg": round(sweep, 1), "residual_r": round(resid, 3),
            })
        i = j + 1
    return out
