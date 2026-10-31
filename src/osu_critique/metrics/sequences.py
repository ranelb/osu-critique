"""Sequence labels: fast-note groups and repeated turn shapes.

The per-object rows already carry time, position, spacing, snap and turn angle,
so the labels people actually name ("doubles", "bursts", "deathstreams",
"squares", "triangles", "zigzags") need no new input. They are kept in their own
block because they are *labels over existing rows*, not measurements: two of them
can describe the same object, and a label is only reported when its bucket
clears the same population gate the rest of the tool uses.

Two families:

runs
    maximal groups of consecutive objects whose gaps are fast (<=250 ms) and
    rhythmically steady (within 35%), classified by group size. The thresholds
    follow the published names rather than a new theory: doubles/triples/quads
    are 2/3/4 notes, bursts 5-9 (osu! tag list), streams 10-31 and deathstreams
    32+ (the cut SimpleBeatmapAnalyzer uses), and ``sustained`` for a long steady
    group that is not stream density (a 1/2 wall is not a deathstream).
    ``find_runs`` is the same
    primitive the stream detector uses, with the velocity term off: a
    jumpstream-shaped 1/2 run has a steady rhythm and a swinging required
    speed, so it lands here rather than in ``metrics.streams``.

shapes
    signed turns over two consecutive legs (tail-aware), grouped into
    ``square`` (~90 deg, same direction), ``triangle`` (~120 deg, same
    direction), ``staircase`` (small same-direction turns) and ``zigzag``
    (alternating direction). Spacing must stay comparable across the window.

Nothing here changes the judgement or invents a rate from a small bucket: each
class reports ``n``, its non-300 count and whether it is ``reported`` (n >= the
adaptive gate). ``standouts`` keeps only reported classes whose rate is at least
1.5x the play's overall rate, or under 0.6x of it -- the contrast rule the rest
of the analysis uses.
"""
from __future__ import annotations

import math
import statistics as st

from .streams import find_runs

FAST_GAP_MS = 250.0
GAP_TOLERANCE = 0.35
MIN_SHAPE_SPACING = 1.0     # below this a "turn" is correction inside the circle
MAX_SPACING_RATIO = 1.9     # three legs within this ratio count as one shape
STANDOUT_HI = 1.5
STANDOUT_LO = 0.6


def gate(n_objects):
    """The adaptive population gate used everywhere (min 8, cap 20, 3%)."""
    return min(20.0, max(8.0, 0.03 * (n_objects or 0)))


def run_class(n, rows=None):
    """Name for a fast group of ``n`` objects (n >= 2).

    A long steady group is only a stream/deathstream when its rhythm is actually
    stream-density: median snap <= 1.5 quarter-beats (1/4 notes) or a median gap
    <= 140 ms. A 1/2 wall at 156 ms is a sustained run, not a deathstream, and
    calling it one makes the label useless.
    """
    if n == 2:
        return "double"
    if n == 3:
        return "triple"
    if n == 4:
        return "quad"
    if n <= 9:
        return "burst"
    rows = rows or []
    snaps = [x.get("snap") for x in rows if x.get("snap")]
    gaps = [rows[i]["t"] - rows[i - 1]["t"] for i in range(1, len(rows))]
    stream_speed = ((st.median(snaps) <= 1.5) if snaps else False) \
        or (bool(gaps) and st.median(gaps) <= 140.0)
    if not stream_speed:
        return "sustained"
    return "stream" if n <= 31 else "deathstream"


def fast_groups(results):
    """Maximal rhythm-steady fast groups (at least two objects).

    ``find_runs`` reports one entry per *gap*, so ``min_notes=1`` is the
    two-object case; the first object of the group is the predecessor carried in
    that entry. ``build`` reconstructs the object list from it.
    """
    return find_runs(results, min_notes=1, max_gap_ms=FAST_GAP_MS,
                     gap_tolerance=GAP_TOLERANCE, velocity_tolerance=None,
                     break_kinds=("Spinner",))


def _end(x):
    tx = x.get("slider_tail_x")
    ty = x.get("slider_tail_y")
    if tx is None:
        tx = x.get("end_x", x["x"])
    if ty is None:
        ty = x.get("end_y", x["y"])
    return float(tx), float(ty)


def signed_turn(a, b, c):
    """Signed turn at ``b`` in degrees: + = left/anticlockwise, - = right.

    Incoming is ``a.end -> b.head``; outgoing is ``b.end -> c.head``, so a
    slider's body direction is part of the turn instead of being skipped.
    """
    ax, ay = _end(a)
    bx, by = _end(b)
    v1 = (b["x"] - ax, b["y"] - ay)
    v2 = (c["x"] - bx, c["y"] - by)
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 <= 1e-6 or n2 <= 1e-6:
        return None
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    return math.degrees(math.atan2(cross, dot))


def _turns(results):
    """``{index: signed turn}`` for objects with two predecessors."""
    return {i: signed_turn(results[i - 2], results[i - 1], results[i])
            for i in range(2, len(results))}


def _similar_spacing(a, b, c):
    vals = [x for x in (a.get("spacing_r"), b.get("spacing_r"),
                        c.get("spacing_r")) if x is not None]
    if len(vals) < 3:
        return False
    lo, hi = min(vals), max(vals)
    return lo >= MIN_SHAPE_SPACING and hi <= lo * MAX_SPACING_RATIO


def _same_sign(vals):
    return all(v > 0 for v in vals) or all(v < 0 for v in vals)


def shape_label(results, i, turns):
    """The shape window ending at object ``i``, or None.

    A window is two turns over three legs (objects ``i-2 .. i``); the labels are
    deliberately coarse. Two consecutive corners are the smallest useful
    evidence -- requiring three (a full square) made the bucket almost empty on
    real maps. Priority: square, triangle, staircase, zigzag, so a window counts
    once.
    """
    if i < 3:
        return None
    ts = [turns.get(i - 1), turns.get(i)]
    if any(t is None for t in ts):
        return None
    wins = [results[i - 2], results[i - 1], results[i]]
    if not _similar_spacing(*wins):
        return None
    mags = [abs(t) for t in ts]
    if all(70 <= m <= 110 for m in mags) and _same_sign(ts):
        return "square"
    if all(105 <= m <= 140 for m in mags) and _same_sign(ts):
        return "triangle"
    if all(20 <= m <= 60 for m in mags) and _same_sign(ts):
        return "staircase"
    if all(60 <= m <= 150 for m in mags) and ts[0] * ts[1] < 0:
        return "zigzag"
    return None


def _rate(rows):
    n = len(rows)
    non300 = sum(1 for x in rows if x.get("result") != "300")
    return n, non300, (non300 / n if n else None)


def _class_row(name, rows, gate_n, overall):
    n, non300, rate = _rate(rows)
    contrast = (rate / overall) if (rate is not None and overall) else None
    return {
        "class": name,
        "n": n,
        "non300": non300,
        "non300_rate": rate,
        "reported": n >= gate_n,
        "contrast": contrast,
        "standout": bool(n >= gate_n and rate is not None and overall is not None
                         and overall > 0
                         and (rate >= STANDOUT_HI * overall
                              or rate <= STANDOUT_LO * overall)),
    }


def build(results):
    """The ``sequences`` block for a run's per-object rows."""
    n_objects = len(results)
    gate_n = gate(n_objects)
    overall = _rate(results)[2]

    run_rows = {}
    run_gaps = {}
    for run in fast_groups(results):
        rows = [run[0][1]] + [x for x, _p, _g, _v in run]
        name = run_class(len(rows), rows)
        run_rows.setdefault(name, []).extend(rows)
        run_gaps.setdefault(name, []).extend(g for _x, _p, g, _v in run)
    runs = []
    for name in ("double", "triple", "quad", "burst", "stream", "deathstream",
                 "sustained"):
        if name not in run_rows:
            continue
        row = _class_row(name, run_rows[name], gate_n, overall)
        gaps = run_gaps.get(name) or []
        row["gap_ms_median"] = float(st.median(gaps)) if gaps else None
        row["share"] = (row["n"] / n_objects) if n_objects else None
        runs.append(row)

    turns = _turns(results)
    labelled = {}
    for i in range(3, n_objects):
        name = shape_label(results, i, turns)
        if name:
            labelled.setdefault(name, []).append(results[i])
    shapes = []
    for name in ("square", "triangle", "staircase", "zigzag"):
        if name not in labelled:
            continue
        row = _class_row(name, labelled[name], gate_n, overall)
        row["share"] = (row["n"] / n_objects) if n_objects else None
        shapes.append(row)

    standouts = [{"family": "runs", **r} for r in runs if r["standout"]] + \
                [{"family": "shapes", **r} for r in shapes if r["standout"]]
    return {
        "gate": gate_n,
        "overall_non300_rate": overall,
        "runs": runs,
        "shapes": shapes,
        "standouts": standouts,
    }


def console_lines(block):
    """Human-readable lines for the sequences block (only reported buckets)."""
    if not block:
        return []
    lines = ["## Sequence labels"]
    runs = [r for r in block.get("runs") or [] if r.get("reported")]
    shapes = [s for s in block.get("shapes") or [] if s.get("reported")]
    if runs:
        lines.append("- fast groups: " + "  ".join(
            f"{r['class']} n={r['n']} non-300 {r['non300_rate'] * 100:.1f}%"
            + (f" ({r['gap_ms_median']:.0f} ms)" if r.get("gap_ms_median") is not None else "")
            for r in runs))
    if shapes:
        lines.append("- turn shapes: " + "  ".join(
            f"{s['class']} n={s['n']} non-300 {s['non300_rate'] * 100:.1f}%"
            for s in shapes))
    for s in block.get("standouts") or []:
        lines.append(f"- contrast: {s['class']} {s['non300_rate'] * 100:.1f}% vs "
                     f"{block['overall_non300_rate'] * 100:.1f}% overall "
                     f"(n={s['n']}, x{s['contrast']:.2f})")
    return lines
