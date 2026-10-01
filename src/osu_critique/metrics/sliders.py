"""Slider bodies, ticks and ends: does the cursor stay on the slider?

The judge is head-only: a slider's judgement comes from the press that started
it, and the 55% of objects that are sliders on the author's maps are otherwise
invisible. This module follows the body instead -- the curve (handling repeats),
the tick points and times, and whether the player stayed inside the follow
circle with the button held -- so a play can say how often sliders were *cut*,
and a dropped slider end is a measured fact rather than a missing number
(``docs/object_schema.md``).

The fields are descriptive (a ``tail_off`` is "the cursor was not on the tail
tick", not "the game counted this as a 100"). The follow rule borrows the
mechanics of ``slider``'s own ``Replay.hits()``:
while pressed you stay *on* within ``FOLLOW_R`` circle radii of the path, and
you only get back *on* within ``RE_ENTRY_R``.

What it is not
--------------
It is **not** used to change the judgement. Measured on the author's replays the
body rule fires far more often than the game degrades sliders (e.g. 150 of the
374 sliders this play scores 300 on RASPUTIN leave the follow circle at some
point, while the recorded counts say the game degraded ~0 of them) -- because a
cursor is *allowed* to cut the body; only the tail matters, and even that is
handled by the head window plus the edge guard in ``assignment.classify``. So
these numbers are reported, and the counts are left to the judgement model.
"""
from __future__ import annotations

import bisect

import numpy as np

FOLLOW_R = 2.4          # stay inside this many radii of the path while pressed
RE_ENTRY_R = 1.0        # ... and this to get back on after leaving
SAMPLE_MS = 4.0         # how finely the body is sampled
MAX_SAMPLES = 400       # ... but never more than this per slider (long sliders)
CUT_PCT = 5.0           # % of the body outside the follow circle = "cut it"


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def path_point(o, t_ms, start_ms, end_ms):
    """The slider's path position at ``t_ms`` (repeats fold back on themselves)."""
    spans = max(1, int(o.repeat))
    dur = end_ms - start_ms
    if dur <= 0:
        p = o.position
        return p.x, p.y
    progress = _clamp((t_ms - start_ms) / dur, 0.0, 1.0) * spans
    span = min(int(progress), spans - 1)
    local = progress - span
    if span % 2 == 1:
        local = 1.0 - local
    pos = o.curve(_clamp(local, 0.0, 1.0))
    return pos.x, pos.y


def tick_points(o, scale):
    """The slider's tick positions and times in real ms (start and end included)."""
    out = []
    try:
        for tp in o.true_tick_points:
            out.append((tp.offset.total_seconds() * 1000.0 * scale, tp.x, tp.y))
    except Exception:                      # exotic curve: no ticks to report
        return []
    out.sort(key=lambda t: t[0])
    return out


def _pressed(frames, times, t):
    i = bisect.bisect_right(times, t) - 1
    if i < 0:
        return False
    f = frames[i]
    return bool(f[3] or f[4])


def follow(o, frames, times, radius, scale, cursor_at, start_ms=None, end_ms=None,
           sample_ms=SAMPLE_MS):
    """Sample one slider's body: how far off it the cursor was, and its ticks."""
    start_ms = (o.time.total_seconds() * 1000.0 * scale) if start_ms is None else start_ms
    end_ms = (o.end_time.total_seconds() * 1000.0 * scale) if end_ms is None else end_ms
    dur = end_ms - start_ms

    off_pct = None
    if dur > 0:
        step = max(sample_ms, dur / MAX_SAMPLES)
        ts = np.arange(start_ms, end_ms + step / 2, step)
        off = 0
        for t in ts:
            px, py = path_point(o, t, start_ms, end_ms)
            c = cursor_at(t)
            if (np.hypot(c[0] - px, c[1] - py) / radius > FOLLOW_R
                    or not _pressed(frames, times, t)):
                off += 1
        off_pct = 100.0 * off / len(ts) if len(ts) else None

    ticks = tick_points(o, scale)
    tick_missed = 0
    tail_missed = None
    for ti, (t, px, py) in enumerate(ticks):
        if t < start_ms - 1 or t > end_ms + 1:
            continue
        c = cursor_at(t)
        missed = (np.hypot(c[0] - px, c[1] - py) / radius > FOLLOW_R
                  or not _pressed(frames, times, t))
        if missed:
            tick_missed += 1
        if ti == len(ticks) - 1:
            tail_missed = bool(missed)

    return {
        "n_ticks": len(ticks),
        "tick_missed": tick_missed,
        "tail_off": tail_missed,
        "off_pct": off_pct,
        "cut": bool(off_pct is not None and off_pct > CUT_PCT),
    }


def annotate(results, raw_objs, frames, times, radius, scale, cursor_at=None):
    """Attach the slider-body fields to the result rows; return the summary block.

    Adds ``slider_tail_off`` / ``slider_missed_ticks`` / ``slider_off_pct`` to
    every slider row (None on circles and spinners) and aggregates the block that
    goes into ``metrics["sliders"]``. These are measurements, not verdicts: see
    the module docstring for why they do not change the judgement.
    """
    from ..io.replay import cursor_at as _cursor_at
    cursor_at = cursor_at or (lambda t: _cursor_at(frames, times, t))
    n = miss = tails = cut = tick_missed = ticks_total = 0
    offs = []
    for i, o in enumerate(raw_objs):
        x = results[i] if i < len(results) else None
        if type(o).__name__ != "Slider":
            continue
        n += 1
        if x is not None and x.get("result") == "miss":
            miss += 1
        body = follow(o, frames, times, radius, scale, cursor_at)
        if x is not None:
            x["slider_tail_off"] = body["tail_off"]
            x["slider_missed_ticks"] = body["tick_missed"]
            x["slider_off_pct"] = body["off_pct"]
        tails += int(bool(body["tail_off"]))
        cut += int(body["cut"])
        tick_missed += body["tick_missed"]
        ticks_total += body["n_ticks"]
        if body["off_pct"] is not None:
            offs.append(body["off_pct"])
    return {
        "n": n,
        "miss": miss,
        "tail_off": tails,
        "cut": cut,
        "cut_pct": (100.0 * cut / n) if n else None,
        "tick_missed": tick_missed,
        "tick_missed_pct": (100.0 * tick_missed / ticks_total) if ticks_total else None,
        "off_pct_median": float(np.median(offs)) if offs else None,
        "follow_r": FOLLOW_R,
        "sample_ms": SAMPLE_MS,
    }
