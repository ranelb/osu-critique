"""Cursor-arrival ("aim mode"): what the hand did, independent of the taps.

Every other aim number in this package is sampled at *press* time, which is the
wrong clock in two cases and a partial one in a third:

- **Relax / Autopilot**: the game taps, so "distance at press time" measures the
  game, not the player. Only the cursor is left -- and it is the cleanest aim
  measurement there is.
- **Dropped / late taps**: a press can land while the cursor is still
  travelling, so press-time aim mixes arrival *timing* into arrival *accuracy*.
- **Everywhere else**: at press time we never look at where the cursor was a
  moment later, which is where the miss actually happened.

This module re-derives the cursor path from the replay frames and measures it at
the **note instant** and at **closest approach** within +/-``WINDOW_MS``: the
distance at the note, when the closest approach happens, the along/lateral split
(did the cursor stop short or go past?), the share of notes the cursor reached
but not on time, and the ceiling curve -- distance at the note against the
cursor speed the jump demands.

The numbers reproduce the reference implementation that used to live in
``scripts/autopsy.py`` (docs/ROADMAP.md item 1): on the author's Relax replay,
0.72 r mean at the note, 0.26 r median closest approach, median peak +10 ms,
16.8 % reached-not-on-time, ceiling 0.47 r at <=1 px/ms rising to 1.19 r above
3 px/ms.

``build_aim`` returns ``(block, rows)``: ``block`` is the JSON-safe summary that
goes into ``metrics["aim_mode"]``; ``rows`` is the per-object measurement the
figures and later analyses read. Nothing here judges: a "miss" is not needed to
measure arrival.
"""
from __future__ import annotations

import math

import numpy as np

WINDOW_MS = 320.0          # how far either side of a note the cursor is followed
SAMPLE_MS = 3.0            # cursor sampling step
LATE_MS = 20.0             # "peaked late/early" threshold, ms vs the note
MIN_BIN = 5                # never report a bin smaller than this

CEILING_EDGES = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 99.0)   # px/ms
JUMP_EDGES = (0.0, 3.0, 5.0, 7.0, 9.0, 99.0)           # circle radii
TIME_BINS = 6


def cursor_rows(objs, frames, times, radius, window_ms=WINDOW_MS,
                sample_ms=SAMPLE_MS):
    """Per-object cursor arrival, sampled from the frames (spinners skipped).

    Each row: ``i`` (object index), ``t``, ``kind``, ``x``/``y`` (centre),
    ``d`` (distance at the note instant, radii), ``dmin`` (best approach),
    ``peak_off`` (when that best approach happens, ms vs the note),
    ``entry_off`` (first sample inside the circle, ms vs the note, or None),
    ``along``/``lat`` (error split along/against the travel axis and sideways),
    ``speed`` (cursor speed the jump *demands*, gap/dt in px/ms) and ``gap_r``
    (jump distance). ``along``/``lat``/``speed``/``gap_r`` are None on the first
    object, which has no predecessor.
    """
    t_arr = np.asarray(times, dtype=float)
    xs = np.array([f[1] for f in frames], dtype=float)
    ys = np.array([f[2] for f in frames], dtype=float)
    rows = []
    for i, o in enumerate(objs):
        if o["kind"] == "Spinner":
            continue
        if t_arr.size == 0:
            continue
        ts = np.arange(o["t"] - window_ms, o["t"] + window_ms + sample_ms / 2,
                       sample_ms)
        if ts.size == 0:
            continue
        px = np.interp(ts, t_arr, xs)
        py = np.interp(ts, t_arr, ys)
        ds = np.hypot(px - o["x"], py - o["y"])
        k = int(ds.argmin())
        inside = np.flatnonzero(ds <= radius)
        cx = float(np.interp(o["t"], t_arr, xs))
        cy = float(np.interp(o["t"], t_arr, ys))
        ex, ey = cx - o["x"], cy - o["y"]
        prev = objs[i - 1] if i else None
        along = lat = speed = gap_r = None
        if prev is not None:
            gap = math.hypot(o["x"] - prev["x"], o["y"] - prev["y"])
            dt = o["t"] - prev["t"]
            if gap > 0:
                ux, uy = (o["x"] - prev["x"]) / gap, (o["y"] - prev["y"]) / gap
                along = (ex * ux + ey * uy) / radius
                lat = abs(-ex * uy + ey * ux) / radius
                gap_r = gap / radius
                if dt and dt > 0:
                    speed = gap / dt
        rows.append({
            "i": i, "t": float(o["t"]), "kind": o["kind"],
            "x": float(o["x"]), "y": float(o["y"]),
            "d": float(math.hypot(ex, ey) / radius),
            "dmin": float(ds[k]) / radius,
            "peak_off": float(ts[k] - o["t"]),
            "entry_off": (float(ts[inside[0]] - o["t"])
                          if inside.size else None),
            "along": along, "lat": lat,
            "speed": speed, "gap_r": gap_r,
        })
    return rows


def _series(rows, key):
    """The present values only (for their own distribution)."""
    return np.array([r[key] for r in rows if r[key] is not None], dtype=float)


def _full(rows, key):
    """One value per row, NaN where unknown -- keeps masks aligned with ``d``."""
    return np.array([np.nan if r[key] is None else r[key] for r in rows],
                    dtype=float)


def _stats(a):
    if a.size == 0:
        return None
    return {"mean": float(a.mean()),
            "median": float(np.median(a)),
            "p10": float(np.percentile(a, 10)),
            "p90": float(np.percentile(a, 90))}


def _pct(a, cond):
    return 100.0 * float(np.mean(cond(a))) if a.size else None


def _bins_table(x, y, edges, min_n=MIN_BIN):
    """Bin ``y`` (distance at the note) by ``x`` (a demand), n-gated."""
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (x >= lo) & (x < hi)
        n = int(sel.sum())
        if n < min_n:
            continue
        out.append({"lo": lo, "hi": hi, "n": n,
                    "mean_r": float(y[sel].mean()),
                    "inside_pct": 100.0 * float((y[sel] <= 1).mean())})
    return out


def summarise(rows, window_ms=WINDOW_MS, sample_ms=SAMPLE_MS, is_relax=False):
    """Aggregate cursor rows into the JSON-safe ``aim_mode`` block."""
    n = len(rows)
    block = {"window_ms": window_ms, "sample_ms": sample_ms, "n": n,
             "is_relax": bool(is_relax), "duration_s": 0.0, "t_start_s": None,
             "distance_at_note_r": None, "closest_approach_r": None,
             "peak_offset_ms": None, "window_entry_ms": None,
             "reached_not_on_time": None, "error_shape": None,
             "ceiling": [], "by_jump_distance": [], "over_time": []}
    if n == 0:
        return block

    d = _series(rows, "d")
    dmin = _series(rows, "dmin")
    peak = _series(rows, "peak_off")
    along = _series(rows, "along")
    lat = _series(rows, "lat")
    ent = _series(rows, "entry_off")
    sp = _full(rows, "speed")
    gapr = _full(rows, "gap_r")
    ok = ~np.isnan(sp)

    block["distance_at_note_r"] = {
        **_stats(d), "inside_pct": _pct(d, lambda a: a <= 1)}
    block["closest_approach_r"] = {
        **_stats(dmin), "inside_pct": _pct(dmin, lambda a: a <= 1),
        "never_inside": int((dmin > 1).sum())}
    block["peak_offset_ms"] = {
        "median": float(np.median(peak)),
        "p10": float(np.percentile(peak, 10)),
        "p90": float(np.percentile(peak, 90)),
        "late_pct": _pct(peak, lambda a: a > LATE_MS),
        "early_pct": _pct(peak, lambda a: a < -LATE_MS)}
    block["window_entry_ms"] = (
        {**_stats(ent), "never_entered": int(n - ent.size)}
        if ent.size else {"never_entered": int(n)})
    band = (dmin <= 1.0) & (d > 1.0)
    block["reached_not_on_time"] = {
        "n": int(band.sum()), "pct": 100.0 * float(band.mean())}
    block["error_shape"] = {
        "along_r": {k: v for k, v in (_stats(along) or {}).items()
                    if k in ("median", "p10", "p90")},
        "lateral_r": {k: v for k, v in (_stats(lat) or {}).items()
                      if k in ("median", "p90")},
        "short_pct": _pct(along, lambda a: a < 0),
        "past_pct": _pct(along, lambda a: a > 0)}

    ceiling = []
    for lo, hi in zip(CEILING_EDGES[:-1], CEILING_EDGES[1:]):
        sel = ok & (sp >= lo) & (sp < hi)
        if int(sel.sum()) < MIN_BIN:
            continue
        ceiling.append({
            "v_lo": lo, "v_hi": hi, "n": int(sel.sum()),
            "mean_r": float(d[sel].mean()),
            "p90_r": float(np.percentile(d[sel], 90)),
            "inside_pct": 100.0 * float((d[sel] <= 1).mean()),
            "peak_ms": float(np.median(peak[sel]))})
    block["ceiling"] = ceiling
    block["by_jump_distance"] = _bins_table(gapr, d, JUMP_EDGES)
    block["over_time"] = _bins_table_over_time(rows, d, peak)
    if rows:
        block["t_start_s"] = round(min(r["t"] for r in rows) / 1000.0, 1)
        block["duration_s"] = round((max(r["t"] for r in rows)
                                     - min(r["t"] for r in rows)) / 1000.0, 1)
    return block


def _bins_table_over_time(rows, d, peak):
    t = np.array([r["t"] for r in rows], dtype=float)
    t0, t1 = float(t[0]), float(t[-1])
    out = []
    if t1 <= t0:
        return out
    for k in range(TIME_BINS):
        a, b = t0 + k * (t1 - t0) / TIME_BINS, t0 + (k + 1) * (t1 - t0) / TIME_BINS
        sel = (t >= a) & (t < b)
        if int(sel.sum()) < MIN_BIN:
            continue
        out.append({
            "t_start": round((a - t0) / 1000.0, 1),
            "t_end": round((b - t0) / 1000.0, 1),
            "n": int(sel.sum()),
            "mean_r": float(d[sel].mean()),
            "p90_r": float(np.percentile(d[sel], 90)),
            "inside_pct": 100.0 * float((d[sel] <= 1).mean()),
            "peak_ms": float(np.median(peak[sel]))})
    return out


def build_aim(objs, frames, times, radius, window_ms=WINDOW_MS,
              sample_ms=SAMPLE_MS, is_relax=False):
    """``cursor_rows`` + ``summarise`` in one call -> ``(block, rows)``."""
    rows = cursor_rows(objs, frames, times, radius, window_ms, sample_ms)
    return summarise(rows, window_ms, sample_ms, is_relax), rows


# ----------------------------------------------------------- presentation ----

def describe(block):
    """Human-readable lines for the aim block (autopsy + console)."""
    n = block.get("n") or 0
    lines = [f"AIM (n={n})"]
    if not n:
        lines.append("  (no non-spinner objects)")
        return lines
    d = block["distance_at_note_r"]
    ca = block["closest_approach_r"]
    pk = block["peak_offset_ms"]
    ent = block["window_entry_ms"]
    rn = block["reached_not_on_time"]
    es = block["error_shape"]
    lines.append(f"  at the note instant: mean {d['mean']:.2f}r median {d['median']:.2f}r "
                 f"p90 {d['p90']:.2f}r | inside the circle {d['inside_pct']:.1f}%")
    lines.append(f"  closest approach +/-{block['window_ms']:.0f}ms: mean {ca['mean']:.2f}r "
                 f"median {ca['median']:.2f}r | inside {ca['inside_pct']:.1f}% "
                 f"| never inside {ca['never_inside']}")
    lines.append(f"  when the peak happens: median {pk['median']:+.0f}ms | "
                 f"{pk['late_pct']:.0f}% late (>{LATE_MS:.0f}ms), {pk['early_pct']:.0f}% early")
    if ent.get("median") is not None:
        lines.append(f"  enters the circle: median {ent['median']:+.0f}ms "
                     f"(p10 {ent['p10']:+.0f} / p90 {ent['p90']:+.0f}) "
                     f"| never entered {ent['never_entered']}")
    lines.append(f"  reached but not on time (dmin<=1r, d>1r): {rn['n']} ({rn['pct']:.1f}%)")
    lines.append(f"  error shape: {es['short_pct']:.0f}% stopped short, "
                 f"{es['past_pct']:.0f}% overshot | along p10 "
                 f"{es['along_r'].get('p10', float('nan')):+.2f} / median "
                 f"{es['along_r'].get('median', float('nan')):+.2f} / p90 "
                 f"{es['along_r'].get('p90', float('nan')):+.2f}r, lateral median "
                 f"{es['lateral_r'].get('median', float('nan')):.2f}r")
    if block["ceiling"]:
        lines.append("  ceiling curve (required cursor speed -> distance at the note):")
        for b in block["ceiling"]:
            lines.append(f"     {b['v_lo']:.1f}-{b['v_hi']:<4.1f} px/ms  n={b['n']:3d}  "
                         f"{b['mean_r']:5.2f}r (p90 {b['p90_r']:5.2f}r)  "
                         f"inside {b['inside_pct']:5.1f}%  peak {b['peak_ms']:+4.0f}ms")
    if block["by_jump_distance"]:
        lines.append("  by jump distance:")
        for b in block["by_jump_distance"]:
            lines.append(f"     {b['lo']:.0f}-{b['hi']:<3.0f}r  n={b['n']:3d}  "
                         f"{b['mean_r']:5.2f}r  inside {b['inside_pct']:5.1f}%")
    if block["over_time"]:
        lines.append(f"  over time ({block.get('duration_s') or 0:.0f}s play):")
        for b in block["over_time"]:
            lines.append(f"     {b['t_start']:5.0f}-{b['t_end']:5.0f}s n={b['n']:3d}  "
                         f"{b['mean_r']:5.2f}r (p90 {b['p90_r']:5.2f}r)  "
                         f"inside {b['inside_pct']:5.1f}%  peak {b['peak_ms']:+4.0f}ms")
    return lines
