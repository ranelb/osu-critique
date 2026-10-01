"""Miss autopsy: not "how did the play go" but "why *these* notes".

The shape-class table, the arrival margin and the per-leg geometry are what
every real finding in this project came out of, and they lived in a throwaway
script. This module makes them part of the pipeline (``metrics["autopsy"]``).

shapes
    every object's 5-note window classified by its turn angles -
    ``near-reversal chain`` (the window is mostly >120 deg turns),
    ``cornered (box)`` (>=2 turns of 55-120 deg), ``flow (arc/line)`` (all gentle)
    or ``mixed`` - with the n-gated off-300 rate, the mean distance at the note
    and the mean jump size per class. The point is the *contrast*: a weakness in
    one shape and not the other names the thing to practise.
arrival_margin_r
    the distance from the centre at **press time** (the "how close to the rim do
    I live" distribution): median, p90/p95/p99, max, and the share pressed
    beyond 0.8 r.
press_vs_arrival_ms
    press time minus the cursor's closest-approach time, per object. Negative
    means the button goes down while the cursor is still travelling - the
    "tapped early, arrived late" mechanism, measurable rather than inferred.
legs
    per-leg heading error (required direction vs the direction the cursor
    actually took between two notes) and path efficiency (straight-line distance
    / distance walked). High headings or low efficiency mean a reading/pathing
    problem; both clean means the problem is timing or speed.
stutter
    presses made mid-travel: more than ``STUTTER_MS`` before the coming object
    while the cursor is still more than ``STUTTER_R`` radii away from it.
misses
    the misses themselves, worst first, each with the nearest press (consumed or
    not), the cursor distance at the note instant and the local geometry - the
    rows the acceptance criteria are written against.

Everything is measurement: a rate is only ``reported`` from ``MIN_SHAPE_N``
windows, and every entry carries its own ``n``.
"""
from __future__ import annotations

import collections
import math

import numpy as np

from ..io.replay import cursor_at
from .profile import aim_px, hit_error

SHAPE_WINDOW = 5            # notes per window: the object and two either side
SHARP_DEG = 120.0           # a turn above this is a near-reversal
CORNER_DEG = 55.0           # ... between this and SHARP_DEG is a corner
MIN_SHAPE_N = 10            # never report a class rate from fewer windows
RIM_R = 0.8                 # "living on the rim" threshold, circle radii
STUTTER_R = 2.5             # mid-travel press: this far from the coming note
STUTTER_MS = 40.0           # ... and at least this early
LEG_SAMPLE_MS = 6.0         # cursor sampling step along one leg
MIN_LEG_R = 1.5             # a leg shorter than this (radii) has no real direction
MAX_MISSES = 25             # keep the metrics JSON bounded


def turn_angle(a, b, c):
    """Turn in degrees between the movement into ``b`` and the movement into ``c``."""
    v1 = (b["x"] - a["x"], b["y"] - a["y"])
    v2 = (c["x"] - b["x"], c["y"] - b["y"])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1 or n2 < 1:
        return None
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def shape_class(objs, i, sharp=SHARP_DEG, corner=CORNER_DEG):
    """Classify the 5-note window around object ``i`` by its turns (None at the edges).

    Turns run from object ``i-1`` to ``i+2``; a turn needs the two objects before
    it, so the earliest usable turn is at index 2 (the original code let the
    ``i == 2`` window wrap to the *last* object of the map).
    """
    if i < 2 or i > len(objs) - 3:
        return None
    turns = [t for t in (turn_angle(objs[k - 2], objs[k - 1], objs[k])
                         for k in range(i - 1, i + 3) if k >= 2)
             if t is not None]
    if len(turns) < 2:
        return None
    n_sharp = sum(1 for t in turns if t > sharp)
    n_corner = sum(1 for t in turns if corner <= t <= sharp)
    if n_sharp >= len(turns) - 1 and n_sharp >= 2:
        return "near-reversal chain"
    if n_corner >= 2:
        return "cornered (box)"
    if all(t < corner for t in turns):
        return "flow (arc/line)"
    return "mixed"


def _row_map(aim_rows):
    return {r["i"]: r for r in (aim_rows or [])}


def _spacing(x):
    v = x.get("spacing_r")
    return None if v is None else float(v)


def shapes(objs, results, aim_rows=None, min_n=MIN_SHAPE_N):
    """Per-class off-300 rates and arrival distance, n-gated."""
    rows = _row_map(aim_rows)
    classes = collections.defaultdict(list)
    for i in range(len(objs)):
        cls = shape_class(objs, i)
        if cls is not None:
            classes[cls].append(i)
    total = sum(len(v) for v in classes.values())
    out = []
    for cls, idxs in sorted(classes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        graded = [results[j]["result"] for j in idxs if j < len(results)]
        ds = [rows[j]["d"] for j in idxs if j in rows]
        gaps = [_spacing(results[j]) for j in idxs
                if j < len(results) and _spacing(results[j]) is not None]
        non300 = sum(1 for r in graded if r != "300")
        out.append({
            "class": cls,
            "n": len(idxs),
            "share": (len(idxs) / total) if total else None,
            "non300": non300,
            "non300_rate": (non300 / len(graded)) if graded else None,
            "mean_d_r": float(np.mean(ds)) if ds else None,
            "mean_gap_r": float(np.mean(gaps)) if gaps else None,
            "reported": len(idxs) >= min_n and bool(graded),
        })
    return {"window": SHAPE_WINDOW, "sharp_deg": SHARP_DEG,
            "corner_deg": CORNER_DEG, "min_n": min_n, "classes": out}


def arrival_margin(results, radius, rim=RIM_R):
    """Press-time distance from the centre, in radii (the rim distribution)."""
    a = np.array([aim_px(x) / radius for x in results if aim_px(x) is not None],
                 dtype=float)
    if a.size == 0:
        return None
    return {"n": int(a.size),
            "median": float(np.median(a)),
            "p90": float(np.percentile(a, 90)),
            "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99)),
            "max": float(a.max()),
            "beyond_rim_pct": 100.0 * float((a > rim).mean())}


def press_vs_arrival(results, aim_rows):
    """Press offset minus closest-approach offset, ms (negative = pressed early)."""
    rows = _row_map(aim_rows)
    diffs = []
    for i, x in enumerate(results):
        err = hit_error(x)
        r = rows.get(i)
        if err is None or r is None:
            continue
        diffs.append(err - r["peak_off"])
    if not diffs:
        return None
    d = np.array(diffs, dtype=float)
    return {"n": int(d.size),
            "median": float(np.median(d)),
            "p10": float(np.percentile(d, 10)),
            "p90": float(np.percentile(d, 90)),
            "pressed_before_arrival_pct": 100.0 * float((d < 0).mean())}


def legs(results_objs, frames, times, radius, sample_ms=LEG_SAMPLE_MS,
         min_leg_r=MIN_LEG_R):
    """Per-leg heading error (deg) and path efficiency (direct / walked).

    Legs shorter than ``min_leg_r`` circle radii are skipped: the "required
    direction" between two objects the cursor barely has to travel between is
    noise (including them produced a 117 deg heading "error" on a leg where the
    cursor moved 2 px), and inside the circle the cursor is correcting, not
    travelling.
    """
    heading, eff = [], []
    objs = results_objs
    for i in range(1, len(objs)):
        p_prev, p_cur = objs[i - 1], objs[i]
        if math.hypot(p_cur["x"] - p_prev["x"],
                      p_cur["y"] - p_prev["y"]) < radius * min_leg_r:
            continue
        req = math.degrees(math.atan2(p_cur["y"] - p_prev["y"],
                                      p_cur["x"] - p_prev["x"]))
        c0 = cursor_at(frames, times, p_prev["t"])
        c1 = cursor_at(frames, times, p_cur["t"])
        act = math.degrees(math.atan2(c1[1] - c0[1], c1[0] - c0[0]))
        heading.append(abs((req - act + 180) % 360 - 180))
        ts = np.arange(p_prev["t"], p_cur["t"], sample_ms)
        pts = [cursor_at(frames, times, t) for t in ts] + [c1]
        walked = sum(math.hypot(pts[j][0] - pts[j - 1][0], pts[j][1] - pts[j - 1][1])
                     for j in range(1, len(pts)))
        direct = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
        if direct > 1:
            eff.append(direct / max(1e-6, walked))
    if not heading:
        return None
    h = np.array(heading, dtype=float)
    out = {"n": int(h.size),
           "heading_err_deg": {"median": float(np.median(h)),
                               "p90": float(np.percentile(h, 90)),
                               "max": float(h.max()),
                               "mean": float(h.mean())}}
    if eff:
        e = np.array(eff, dtype=float)
        out["path_efficiency"] = {"n": int(e.size), "median": float(np.median(e)),
                                  "p10": float(np.percentile(e, 10)),
                                  "below_70pct_pct": 100.0 * float((e < 0.7).mean())}
    return out


def stutter(frames, times, presses, objs, radius, stutter_r=STUTTER_R,
            stutter_ms=STUTTER_MS):
    """Presses made mid-travel: early, with the cursor still far from the note."""
    if not presses or not objs:
        return None
    n = 0
    for p, _key in presses:
        j = min(range(len(objs)), key=lambda k: abs(objs[k]["t"] - p))
        if p < objs[j]["t"] and (objs[j]["t"] - p) > stutter_ms:
            c = cursor_at(frames, times, p)
            if math.hypot(c[0] - objs[j]["x"], c[1] - objs[j]["y"]) / radius > stutter_r:
                n += 1
    return {"n": n, "presses": len(presses),
            "pct": 100.0 * n / len(presses),
            "threshold_r": stutter_r, "min_early_ms": stutter_ms}


def _nearest_press(presses, t, w50):
    """The nearest press to time ``t`` inside the 50-window (consumed or not)."""
    best, best_d = None, None
    for p, key in presses or []:
        d = p - t
        if abs(d) <= w50 and (best_d is None or abs(d) < abs(best_d)):
            best, best_d = (p, key), d
    if best is None:
        return None
    return {"press_ms": best_d, "key": best[1]}


def misses(results, objs, presses, aim_rows, radius, w50, frames=None, times=None,
           limit=MAX_MISSES):
    """Every miss with its arrival context; worst (furthest at the note) first."""
    rows = _row_map(aim_rows)
    out = []
    for i, x in enumerate(results):
        if x.get("result") != "miss":
            continue
        o = objs[i]
        r = rows.get(i, {})
        near = _nearest_press(presses, o["t"], w50)
        aim_press = (float(aim_px(x)) / radius
                     if aim_px(x) is not None else None)
        if aim_press is None and near is not None and frames is not None:
            c = cursor_at(frames, times, o["t"] + near["press_ms"])
            aim_press = math.hypot(c[0] - o["x"], c[1] - o["y"]) / radius
        out.append({
            "i": i,
            "t": round(float(o["t"]), 1),
            "kind": o["kind"],
            "d_r": r.get("d"),
            "closest_r": r.get("dmin"),
            "aim_at_press_r": aim_press,
            "press_ms": near["press_ms"] if near else None,
            "key": near["key"] if near else None,
            "gap_r": _spacing(x),
            "turn_deg": x.get("angle_deg"),
            "speed": (r.get("speed")),
        })
    out.sort(key=lambda m: -(m["d_r"] if m["d_r"] is not None else -1))
    return {"n": len(out), "rows": out[:limit]}


def build(objs, results, frames, times, radius, aim_rows=None, presses=None,
          w50=None, is_relax=False):
    """Assemble the miss-autopsy block (``metrics["autopsy"]``)."""
    relax = bool(is_relax)
    return {
        "is_relax": relax,
        "shapes": shapes(objs, results, aim_rows),
        "arrival_margin_r": None if relax else arrival_margin(results, radius),
        "press_vs_arrival_ms": None if relax else press_vs_arrival(results, aim_rows),
        "legs": legs(objs, frames, times, radius),
        "stutter": None if relax else stutter(frames, times, presses, objs, radius),
        "misses": misses(results, objs, None if relax else presses, aim_rows,
                         radius, w50 or 250.0, frames=frames, times=times),
    }


# ----------------------------------------------------------- presentation ----

def console_lines(block):
    """Two or three short lines for the console summary."""
    out = []
    classes = [c for c in (block.get("shapes") or {}).get("classes", []) if c["reported"]]
    if classes:
        out.append("  shapes (5-note windows, off-300): " + "  ".join(
            f"{c['class']} {100 * c['non300_rate']:.1f}% (n={c['n']})" for c in classes))
    bits = []
    if block.get("arrival_margin_r"):
        m = block["arrival_margin_r"]
        bits.append(f"arrival margin median {m['median']:.2f}r "
                    f"({m['beyond_rim_pct']:.1f}% beyond {RIM_R:.1f}r)")
    if block.get("press_vs_arrival_ms"):
        p = block["press_vs_arrival_ms"]
        bits.append(f"press-vs-arrival {p['median']:+.0f}ms median "
                    f"({p['pressed_before_arrival_pct']:.0f}% early)")
    if block.get("legs"):
        h = block["legs"]["heading_err_deg"]
        bits.append(f"legs {h['median']:.0f}deg heading median")
    if block.get("stutter"):
        s = block["stutter"]
        bits.append(f"stutter {s['pct']:.1f}%")
    if bits:
        out.append("  " + " | ".join(bits))
    ms = block.get("misses") or {}
    if ms.get("n"):
        worst = ms["rows"][0] if ms["rows"] else None
        line = f"  misses {ms['n']}"
        if worst:
            line += (f" (worst #{worst['i']} {worst['kind']} at "
                     f"{(worst['d_r'] if worst['d_r'] is not None else 0):.2f}r"
                     + (f", press {worst['press_ms']:+.0f}ms" 
                        if worst["press_ms"] is not None else "") + ")")
        out.append(line)
    return out


def describe(block):
    """Human-readable lines for the autopsy block."""
    lines = []
    sh = block.get("shapes") or {}
    classes = sh.get("classes") or []
    if classes:
        lines.append("SHAPES (%d-note windows)" % sh.get("window", SHAPE_WINDOW))
        for c in classes:
            rate = ("%.1f%%" % (100 * c["non300_rate"])
                    if c["non300_rate"] is not None else "--")
            d = ("%.2fr" % c["mean_d_r"]) if c["mean_d_r"] is not None else "--"
            gap = ("%.2fr" % c["mean_gap_r"]) if c["mean_gap_r"] is not None else "--"
            lines.append(f"  {c['class']:22s} n={c['n']:3d}  distance at note {d}  "
                         f"gap {gap}  non-300 {c['non300']} ({rate})"
                         + ("" if c["reported"] else "  [n<%d]" % sh.get("min_n", 10)))
    if block.get("arrival_margin_r"):
        m = block["arrival_margin_r"]
        lines.append(f"ARRIVAL MARGIN at press (n={m['n']}): median {m['median']:.2f}r "
                     f"p90 {m['p90']:.2f}r p99 {m['p99']:.2f}r max {m['max']:.2f}r | "
                     f"beyond {RIM_R:.1f}r {m['beyond_rim_pct']:.1f}%")
    if block.get("press_vs_arrival_ms"):
        p = block["press_vs_arrival_ms"]
        lines.append(f"PRESS vs ARRIVAL (n={p['n']}): median {p['median']:+.0f}ms "
                     f"(p10 {p['p10']:+.0f} / p90 {p['p90']:+.0f}) | "
                     f"{p['pressed_before_arrival_pct']:.0f}% pressed before the cursor arrived")
    if block.get("legs"):
        g = block["legs"]
        h = g["heading_err_deg"]
        line = (f"LEGS (n={g['n']}): heading error median {h['median']:.0f}deg "
                f"(p90 {h['p90']:.0f}deg, max {h['max']:.0f}deg)")
        if g.get("path_efficiency"):
            e = g["path_efficiency"]
            line += (f" | path efficiency median {e['median']:.2f} "
                     f"(<0.7 in {e['below_70pct_pct']:.1f}% of legs)")
        lines.append(line)
    if block.get("stutter"):
        s = block["stutter"]
        lines.append(f"STUTTER (mid-travel presses, cursor >{s['threshold_r']}r from the "
                     f"note and >{s['min_early_ms']:.0f}ms early): {s['n']} of "
                     f"{s['presses']} ({s['pct']:.1f}%)")
    ms = block.get("misses") or {}
    if ms.get("n"):
        lines.append(f"MISSES ({ms['n']}, worst first)")
        for m in ms["rows"]:
            press = (f"press {m['press_ms']:+.0f}ms" if m["press_ms"] is not None
                     else "no press")
            aim = (f"aim {m['aim_at_press_r']:.2f}r"
                   if m["aim_at_press_r"] is not None else "aim --")
            d = f"{m['d_r']:.2f}r" if m["d_r"] is not None else "--"
            turn = f"{m['turn_deg']:.0f}deg" if m["turn_deg"] is not None else "--"
            gap = f"{m['gap_r']:.1f}r" if m["gap_r"] is not None else "--"
            lines.append(f"  #{m['i']:4d} t={m['t'] / 1000:6.1f}s {m['kind']:6s} "
                         f"at the note {d} | {press} {aim} | gap {gap} turn {turn}")
    return lines
