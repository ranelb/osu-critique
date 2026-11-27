"""Leg descriptors: what every object is, even when no shape names it.

``geometry`` names a run of objects only when it draws a recognisable shape and
leaves the rest unlabelled on purpose (Obsession: 10 % covered, because it is
wide jumps with no repeating figure). That is honest, but a replay-side join
needs a category for *every* object. This module supplies it from three
measurements per leg, with no shape detector involved:

distance
    how far the cursor travels (previous object's exit -> this head), in circle
    radii: ``touching`` / ``close`` / ``medium`` / ``wide``.
flow
    how sharply the heading changes entering this leg: ``flow`` (continues
    smoothly), ``angle`` (a real corner) or ``snap`` (near reversal). Legs with no
    direction (shorter than ``min_leg_r``) are ``none``; a turn is only defined
    between two legs that both have one.
tempo
    the real gap in ms, ``fast`` / ``mid`` / ``slow`` with the same ceilings
    ``rhythm`` uses (160 / 250 ms). The word "stream" is deliberately not used:
    150 ms wide jumps are a 1/2 jump section at 200 BPM, not a stream. The gap in
    beats is carried when the local beat length is known, so a label can say
    ``1/2`` honestly.

Maximal runs of legs sharing distance and tempo form a *descriptor segment*; its
flow is the dominant class of the legs that have a direction (``mixed`` when no
class holds ``flow_share`` of them), so one stray corner does not split a run of
wide snaps ("wide snap fast"). Same conventions as ``geometry``: legs run from one object's
exit to the next head (slider tails count), the turn is signed (positive =
clockwise as drawn, since osu! y points down), spinners break a run.

Everything is deterministic and local; every threshold is in ``TABLE``.
"""
from __future__ import annotations

import math
import statistics as st

from .rhythm import BURST_MAX_GAP, STREAM_MAX_GAP

TABLE = {
    "min_leg_r": 1.5,       # shorter legs have no direction (ROADMAP)
    "touching_r": 1.0,      # under this the notes overlap: a stack or a tap in place
    "close_r": 3.0,         # up to here: close; beyond: medium
    "wide_r": 6.0,          # beyond this: wide
    "flow_max": 45.0,       # |turn| up to this keeps the heading: flow
    "angle_max": 120.0,     # up to here a corner; beyond it a near reversal: snap
    "min_run": 3,           # legs a descriptor segment needs
    "flow_share": 0.6,      # a segment's flow is the class holding this share of its directed legs
}

DIST = ("touching", "close", "medium", "wide")
FLOW = ("none", "flow", "angle", "snap")
TEMPO = ("fast", "mid", "slow")


def _wrap(deg):
    deg = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if deg == -180.0 else deg


def _end(o):
    return o.get("end_x", o["x"]), o.get("end_y", o["y"])


def dist_class(r):
    t = TABLE
    if r < t["touching_r"]:
        return "touching"
    if r < t["close_r"]:
        return "close"
    if r < t["wide_r"]:
        return "medium"
    return "wide"


def flow_class(turn):
    if turn is None:
        return "none"
    a = abs(turn)
    if a <= TABLE["flow_max"]:
        return "flow"
    if a <= TABLE["angle_max"]:
        return "angle"
    return "snap"


def tempo_class(gap_ms):
    if gap_ms <= STREAM_MAX_GAP:
        return "fast"
    if gap_ms <= BURST_MAX_GAP:
        return "mid"
    return "slow"


def legs(objs, radius, beat_at=None):
    """One record per object ``i >= 1``: the leg that arrives at it (None at a spinner)."""
    n = len(objs)
    out = [None] * n
    ang = [None] * n
    for i in range(1, n):
        a, b = objs[i - 1], objs[i]
        if a["kind"] == "Spinner" or b["kind"] == "Spinner":
            continue
        ex, ey = _end(a)
        dx, dy = b["x"] - ex, b["y"] - ey
        r = math.hypot(dx, dy) / radius
        if r >= TABLE["min_leg_r"]:
            ang[i] = math.degrees(math.atan2(dy, dx))
        gap = b["t"] - a["t"]          # head to head, like streams.find_runs
        turn = None
        if ang[i] is not None and i >= 2 and ang[i - 1] is not None:
            turn = _wrap(ang[i] - ang[i - 1])
        beats = None
        if beat_at is not None:
            bl = beat_at(a["t"])
            beats = gap / bl if bl else None
        out[i] = {
            "dist_r": r, "dist": dist_class(r),
            "turn_deg": turn, "flow": flow_class(turn),
            "gap_ms": gap, "beats": beats, "tempo": tempo_class(gap),
        }
    return out


def _key(leg):
    return (leg["dist"], leg["tempo"])


def _seg_flow(seg):
    directed = [x["flow"] for x in seg if x["flow"] != "none"]
    if not directed:
        return "none"
    top = max(FLOW[1:], key=directed.count)
    return top if directed.count(top) / len(directed) >= TABLE["flow_share"] else "mixed"


def label(dist, flow, tempo, beats=None):
    flow_word = "" if flow == "none" else f" {flow}"
    div = ""
    if beats:
        div = f" ({_divisor(beats)})"
    return f"{dist}{flow_word} {tempo}{div}"


def _divisor(beats):
    """1/n for the nearest common divisor, else the raw beat fraction."""
    for d in (1, 2, 3, 4, 6, 8):
        if abs(beats - 1.0 / d) <= 0.12 / d:
            return f"1/{d}"
    return f"{beats:.2f} beat"


def segments(objs, leg_rows):
    """Maximal runs of at least ``min_run`` legs with the same distance and tempo."""
    out, i, n = [], 1, len(objs)
    while i < n:
        if leg_rows[i] is None:
            i += 1
            continue
        k = _key(leg_rows[i])
        j = i
        while j + 1 < n and leg_rows[j + 1] is not None and _key(leg_rows[j + 1]) == k:
            j += 1
        if j - i + 1 >= TABLE["min_run"]:
            seg = leg_rows[i:j + 1]
            flow = _seg_flow(seg)
            bs = [x["beats"] for x in seg if x["beats"]]
            beats = st.median(bs) if bs else None
            out.append({
                "start": i, "end": j, "n": j - i + 1, "dist": k[0], "flow": flow,
                "tempo": k[1], "label": label(k[0], flow, k[1], beats),
                "t0": objs[i]["t"], "t1": objs[j]["t"],
                "dist_r_median": st.median(x["dist_r"] for x in seg),
                "gap_ms_median": st.median(x["gap_ms"] for x in seg),
                "beats_median": beats,
            })
        i = j + 1
    return out


def describe(objs, radius, beat_at=None):
    """``{"legs", "segments", "summary"}`` for a map's ``build_objects`` rows."""
    rows = legs(objs, radius, beat_at)
    segs = segments(objs, rows)
    for s in segs:
        for i in range(s["start"], s["end"] + 1):
            rows[i]["segment"] = s["label"]
    n_legs = sum(1 for r in rows if r)
    covered = sum(s["n"] for s in segs)
    by = {}
    for s in segs:
        row = by.setdefault(s["label"], {"segments": 0, "legs": 0})
        row["segments"] += 1
        row["legs"] += s["n"]
    return {
        "legs": rows, "segments": segs,
        "summary": {
            "n_legs": n_legs, "covered": covered,
            "coverage": covered / n_legs if n_legs else 0.0,
            "labels": by,
            "dist": _count(rows, "dist", DIST), "flow": _count(rows, "flow", FLOW),
            "tempo": _count(rows, "tempo", TEMPO),
        },
    }


def _count(rows, field, order):
    c = {k: 0 for k in order}
    for r in rows:
        if r:
            c[r[field]] += 1
    return c
