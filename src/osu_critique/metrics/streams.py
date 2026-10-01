"""Stream/burst detection: rhythm continuity and velocity continuity.

The old rule was ">=4 consecutive circles with <=4r spacing" - *spacing* standing
in for speed, which misfires in both directions: it called 1/2 filler runs streams
on Bang Bang (where the real speed material is 1/8 slider-jumps) and it was blind
to slider-interleaved bursts (0 segments on MONTAGEM, whose runs are ~6r wide).

A run is now found by what it *is*: consecutive objects whose gaps stay steady
(within ``GAP_TOLERANCE`` of the running gap - the primitive the map profile
already used for ``chains``) whose required cursor speed ``spacing / dt`` stays
within ``VELOCITY_TOLERANCE`` of the run's median, at a gap no slower than
``MAX_GAP_MS``. Any object kind counts (sliders included); spinners break a run,
because nothing is tapped through them and their "required speed" is meaningless.

Every segment then reports the numbers that say what the material actually was -
median gap, notes per second, required speed, the kind mix - instead of a verdict
the detector cannot support. ``profile._chains`` calls the same ``find_runs`` with
the velocity term off, so the two views cannot drift apart.
"""
from __future__ import annotations

import collections
import statistics as st

import numpy as np

MIN_NOTES = 4               # a run is at least this many objects
MAX_GAP_MS = 250.0          # slower than this and it is not sustained pressure
GAP_TOLERANCE = 0.35        # consecutive gaps within +/-35% of the running gap
VELOCITY_TOLERANCE = 0.40   # required speed within +/-40% of the run's median
BREAK_KINDS = ("Spinner",)  # nothing is tapped through a spinner


def _velocity(x, gap_ms):
    """Required cursor speed in circle radii per ms (None when unknown)."""
    spacing = x.get("spacing_r")
    if spacing is None or gap_ms is None or gap_ms <= 0:
        return None
    return spacing / gap_ms


def find_runs(results, min_notes=MIN_NOTES, max_gap_ms=MAX_GAP_MS,
              gap_tolerance=GAP_TOLERANCE, velocity_tolerance=None,
              break_kinds=BREAK_KINDS):
    """Maximal runs of consecutive objects with a steady gap (and steady speed).

    Returns a list of runs; each run is a list of ``(row, prev, gap_ms,
    velocity)``. ``velocity_tolerance=None`` turns the velocity term off, which is
    how ``profile._chains`` reproduces its own historical numbers exactly.
    """
    runs, run = [], []
    prev = None
    for x in results:
        gap = None if prev is None else x["t"] - prev["t"]
        prev = x
        if gap is None or gap <= 0:
            continue                       # not a gap: neither joins nor breaks a run
        if break_kinds and x.get("kind") in break_kinds:
            if len(run) >= min_notes:
                runs.append(run)
            run = []
            continue
        vel = _velocity(x, gap)
        fast = gap <= max_gap_ms
        steady = (not run) or abs(gap - run[-1][2]) <= gap_tolerance * max(gap, run[-1][2])
        continuous = True
        if velocity_tolerance is not None and run:
            vels = [v for _x, _p, _g, v in run if v is not None]
            if vel is None or not vels:
                continuous = False
            else:
                med = st.median(vels)
                continuous = abs(vel - med) <= velocity_tolerance * max(vel, med)
        if fast and steady and continuous:
            run.append((x, prev, gap, vel))
        else:
            if len(run) >= min_notes:
                runs.append(run)
            run = [(x, prev, gap, vel)] if fast else []
    if len(run) >= min_notes:
        runs.append(run)
    return runs


def stream_stats(results, min_notes=MIN_NOTES, max_gap_ms=MAX_GAP_MS,
                 gap_tolerance=GAP_TOLERANCE,
                 velocity_tolerance=VELOCITY_TOLERANCE):
    """Per-segment timing, alternation and material for every run of sustained notes."""
    out = []
    for s in find_runs(results, min_notes, max_gap_ms, gap_tolerance,
                       velocity_tolerance):
        rows = [x for x, _p, _g, _v in s]
        errs = [x["error"] for x in rows if x.get("error") is not None]
        keys = [x["key"] for x in rows if x.get("key")]
        same_key = sum(1 for a, b in zip(keys, keys[1:]) if a == b)
        gaps = [g for _x, _p, g, _v in s]
        vels = [v for _x, _p, _g, v in s if v is not None]
        kinds = collections.Counter(x["kind"] for x in rows)
        span = rows[-1]["t"] - rows[0]["t"]   # n-1 gaps across the run
        out.append({
            "t_start": round(rows[0]["t"], 1),
            "t_end": round(rows[-1]["t"], 1),
            "n": len(rows),
            "miss": sum(1 for x in rows if x["result"] == "miss"),
            "mean_err": float(np.mean(errs)) if errs else None,
            "std_err": float(np.std(errs)) if errs else None,
            "alt_ratio": 1 - same_key / max(1, len(keys) - 1),
            "key_pattern": "".join(keys)[:60],
            # what the material was, in the units that say it
            "gap_ms": (st.median(gaps) if gaps else None),
            "notes_per_s": (1000.0 * (len(rows) - 1) / span) if span > 0 else None,
            "velocity_r_ms": (float(st.median(vels)) if vels else None),
            "kinds": dict(kinds),
        })
    return out


def summarise(segments):
    """Aggregate a segment list: how much sustained material there was, and how hard.

    A consumer should not have to walk the segments to say "12 runs, 59 notes, a
    median 6.5 notes/s at 0.03 r/ms" - and the pressure percentiles are what make
    "streams" comparable between maps of different difficulty.
    """
    if not segments:
        return {"notes": 0, "misses": 0, "gap_ms_median": None,
                "notes_per_s_p50": None, "notes_per_s_p90": None,
                "velocity_r_ms_p50": None, "velocity_r_ms_p90": None,
                "kinds": {}}
    notes = [s["n"] for s in segments]
    nps = [s["notes_per_s"] for s in segments if s["notes_per_s"]]
    vel = [s["velocity_r_ms"] for s in segments if s["velocity_r_ms"]]
    gaps = [s["gap_ms"] for s in segments if s["gap_ms"]]
    kinds = collections.Counter()
    for s in segments:
        kinds.update(s.get("kinds") or {})
    return {
        "notes": sum(notes),
        "misses": sum(s["miss"] for s in segments),
        "gap_ms_median": float(st.median(gaps)) if gaps else None,
        "notes_per_s_p50": float(np.percentile(nps, 50)) if nps else None,
        "notes_per_s_p90": float(np.percentile(nps, 90)) if nps else None,
        "velocity_r_ms_p50": float(np.percentile(vel, 50)) if vel else None,
        "velocity_r_ms_p90": float(np.percentile(vel, 90)) if vel else None,
        "kinds": dict(kinds),
    }
