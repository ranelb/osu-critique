"""Map/pattern profile: rhythm rate, composition, stamina and per-family timing.

Everything here is derived from the per-object records (``structure.py``) plus
the map's own geometry -- no new inputs. It exists because the per-play
aggregates answer "how did I do" but never "what was I actually playing":

rate
    the effective BPM in game (map BPM / scale), the note gaps in real ms and
    that gap as a multiple of the 300-window. "1/8 snap" means nothing without
    it: 78 ms per note against a 29 ms window is not the same map as 78 ms
    against a 92 ms window.
composition
    families of the form ``<kind>_<divisor>_<spacing>`` with their share of the
    objects and their n-gated hit rates, plus the character of the map's sliders
    (path length, repeats and the cursor speed the slider demands).
stamina
    the load over time: notes per second in short bins, how long the play stays
    above a threshold, and where the breaks are.
timing_by_family
    signed bias and spread per family -- one global bias hides that a player can
    arrive 20 ms late on 1/2 jumps and tap 20 ms early on slow notes.
chains
    runs of consecutive objects with a steady gap (>=4 notes): the places where
    sustained tapping is actually required, with performance by chain position.
context
    what preceded each object (circle / short slider / long slider / spinner).
"""
from __future__ import annotations

import collections
import statistics as st

from .streams import find_runs

def hit_error(x):
    """Signed hit error in ms, from a pipeline row or a written record."""
    return x["error_ms"] if "error_ms" in x else x.get("error")


def end_time(x):
    return x["end_t"] if "end_t" in x else x.get("end")


def aim_px(x):
    return x["aim_px"] if "aim_px" in x else x.get("aim")


DIVISORS = ((16, "1/16"), (12, "1/12"), (8, "1/8"), (6, "1/6"), (4, "1/4"),
            (3, "1/3"), (2, "1/2"), (1.3333, "dotted"), (1.0, "1/1"))

MIN_FAMILY_N = 10


def divisor(beats):
    """osu! divisor label for a gap of ``beats`` beats (None when off-grid)."""
    if beats is None or beats <= 0:
        return None
    d = 1.0 / beats
    best, err = None, 9.0
    for value, label in DIVISORS:
        e = abs(d - value) / value
        if e < err:
            best, err, lab = value, e, label
    return lab if err <= 0.15 else None


def beats_label(beats):
    """Human label for a gap: the osu! divisor, else an explicit beat count."""
    if beats is None:
        return "unknown"
    beats = round(beats, 2)               # snap is a float: 1.9999 beats is 2 beats
    if beats >= 1.01:                     # slower than one beat: a count, not a divisor
        return f"{beats:g} beats"
    lab = divisor(beats)
    return lab or f"{beats:g} beats"


def spacing_class(spacing_r):
    if spacing_r is None:
        return "unknown"
    if spacing_r <= 2.0:
        return "dense"
    if spacing_r <= 4.0:
        return "spaced"
    return "jump"


def family(x):
    """``<kind>_<divisor>_<spacing>`` -- the pattern family of one object.

    Kind: ``circle`` / ``slider`` / ``spinner``. Divisor comes from the gap to
    the previous object start, so a family means "this object arrives <divisor>
    after the previous one, at <spacing> distance". Objects whose gap is
    off-grid get an explicit beat count (``circle_2.0-beats_jump``).
    """
    if x["kind"] == "Spinner":
        return "spinner"
    beats = beats_of(x)
    if beats is None:
        return "start"
    lab = beats_label(beats).replace(" ", "-")
    return f"{x['kind'].lower()}_{lab}_{spacing_class(x.get('spacing_r'))}"


def beats_of(x):
    """Gap to the previous object in beats (snap is stored in quarter-beats)."""
    snap = x.get("snap")
    if not snap:
        return None
    return snap / 4.0


def _rows(results):
    """Per-object (x, prev, gap_ms, beats) rows, skipping the first object."""
    rows, prev = [], None
    for x in results:
        gap = None if prev is None else x["t"] - prev["t"]
        rows.append((x, prev, gap, beats_of(x)))
        prev = x
    return rows


def _rate(results, windows):
    """Effective BPM, real note gaps, and the gap against the 300-window."""
    gaps = [(x["t"] - prev["t"]) for x, prev, gap, _b in _rows(results) if gap and gap > 0]
    bpm_eff = [x["bpm_eff"] for x in results if x.get("bpm_eff")]
    span_s = (results[-1]["t"] - results[0]["t"]) / 1000.0 if len(results) > 1 else 0.0
    snap_mix = collections.Counter(beats_label(beats_of(x)) for x in results
                                   if beats_of(x) is not None)
    q = lambda p: (sorted(gaps)[min(len(gaps) - 1, int(p * len(gaps)))] if gaps else None)
    w300 = (windows or {}).get("300")
    return {
        "effective_bpm": {"min": min(bpm_eff) if bpm_eff else None,
                          "median": st.median(bpm_eff) if bpm_eff else None,
                          "max": max(bpm_eff) if bpm_eff else None},
        "note_gap_ms": {"p10": q(.10), "median": q(.50), "p90": q(.90)},
        "notes_per_second": {"mean": (len(gaps) / span_s) if span_s else None,
                             "median_gap_based": (1000.0 / st.median(gaps)) if gaps else None},
        "gap_vs_300_window": {"p10_ratio": (q(.10) / w300) if gaps and w300 else None,
                              "median_ratio": (q(.50) / w300) if gaps and w300 else None},
        "snap_mix": dict(snap_mix.most_common()),
    }


def _family_rows(results, min_n=MIN_FAMILY_N, radius=None):
    groups = collections.defaultdict(list)
    for x in results:
        groups[family(x)].append(x)
    total = len(results) or 1
    out = []
    for fam, g in groups.items():
        nb = sum(1 for x in g if x["result"] != "300")
        errs = [hit_error(x) for x in g if hit_error(x) is not None]
        aims = [aim_px(x) / radius for x in g
                if radius and aim_px(x) is not None]
        out.append({"family": fam, "n": len(g), "share": len(g) / total,
                    "non300": nb, "non300_rate": nb / len(g),
                    "mean_err_ms": st.mean(errs) if errs else None,
                    "std_err_ms": st.pstdev(errs) if len(errs) > 1 else None,
                    "mean_aim_r": st.mean(aims) if aims else None,
                    "reported": len(g) >= min_n})
    return sorted(out, key=lambda d: -d["n"])


def _sliders(bm, scale):
    """Character of the map's sliders: how far and how fast the cursor must go."""
    rows = []
    for o in bm.hit_objects():
        if type(o).__name__ != "Slider":
            continue
        # pixel_length is absent on some parsed sliders; length is always there
        length = float(getattr(o, "pixel_length", None)
                       or getattr(o, "length", None) or 0)
        repeats = max(1, int(getattr(o, "repeat", 1) or 1))
        dur = max(1e-6, (o.end_time - o.time).total_seconds() * 1000.0 * scale)
        rows.append((length, repeats, dur, length / (dur / repeats)))
    if not rows:
        return {"n": 0}
    length = sorted(r[0] for r in rows)
    speed = sorted(r[3] for r in rows)
    pick = lambda s, p: s[min(len(s) - 1, int(p * len(s)))]
    return {
        "n": len(rows),
        "length_px": {"p10": pick(length, .10), "median": pick(length, .50),
                      "p90": pick(length, .90)},
        "cursor_speed_px_ms": {"p10": pick(speed, .10), "median": pick(speed, .50),
                               "p90": pick(speed, .90)},
        "long_path_share": sum(1 for r in rows if r[0] >= 100) / len(rows),
        "repeats_share": sum(1 for r in rows if r[1] > 1) / len(rows),
    }


def _stamina(results, bin_s=5.0):
    """Notes per second over time, above-threshold time, longest run and breaks."""
    if len(results) < 2:
        return {}
    t0, t1 = results[0]["t"], results[-1]["t"]
    span = max(1.0, t1 - t0)
    n_bins = max(1, int(span / (bin_s * 1000)))
    bins = []
    for k in range(n_bins):
        a = t0 + k * span / n_bins
        b = t0 + (k + 1) * span / n_bins
        n = sum(1 for x in results if a <= x["t"] < b)
        bins.append({"t_start": a, "t_end": b, "notes_per_second": n / ((b - a) / 1000.0)})
    nps = [b["notes_per_second"] for b in bins]
    rates = sorted(1000.0 / max(1e-6, x["t"] - p["t"])
                   for x, p in zip(results[1:], results[:-1]))
    run = best = 0
    best_start = start = None
    limit = 1000.0 / 6.0            # >= 6 notes/s
    for x, p in zip(results[1:], results[:-1]):
        if 0 < (x["t"] - p["t"]) <= limit:
            if run == 0:
                start = p["t"]
            run += 1
            if run > best:
                best, best_start = run, start
        else:
            run = 0
    breaks = [{"t_start": b["t_start"], "t_end": b["t_end"]}
              for b in bins if b["notes_per_second"] < 1.0]
    return {
        "bin_seconds": bin_s,
        "bins": bins,
        "peak_notes_per_second": max(nps) if nps else None,
        "mean_notes_per_second": st.mean(nps) if nps else None,
        "seconds_above_6nps": sum(b["notes_per_second"] > 6 for b in bins) * bin_s,
        "longest_sustained": {"notes": best, "seconds": best * limit / 1000.0,
                              "t_start": best_start} if best else None,
        "p90_gap_ms": rates[int(0.1 * len(rates))] if rates else None,
        "breaks": breaks,
    }


def _chains(results, min_notes=4, max_gap_ms=250.0, tolerance=0.35):
    """Runs of >=``min_notes`` consecutive objects with a steady fast gap.

    Rhythm continuity (consecutive gaps within +/-``tolerance``) instead of the
    old ">=4 circles with <=4r spacing": that rule called 1/2 filler runs
    "streams" while ignoring slider-interleaved speed material. The primitive
    lives in ``metrics.streams.find_runs`` (which the stream detector also uses,
    with its velocity term on) so the two views cannot drift apart.
    """
    chains = [list(r) for r in find_runs(results, min_notes, max_gap_ms, tolerance,
                                         velocity_tolerance=None, break_kinds=())]

    by_pos = collections.defaultdict(lambda: [0, 0])
    worst = []
    for c in chains:
        for i, (x, _p, _g, _v) in enumerate(c):
            key = "1-4" if i < 4 else ("5-8" if i < 8 else ("9-12" if i < 12 else "13+"))
            by_pos[key][0] += 1
            by_pos[key][1] += 1 if x["result"] != "300" else 0
        nb = sum(1 for x, _p, _g, _v in c if x["result"] != "300")
        worst.append({"t_start": c[0][0]["t"], "notes": len(c), "non300": nb,
                      "gap_ms": st.median([g for _x, _p, g, _v in c]),
                      "family": family(c[0][0])})
    return {
        "n_chains": len(chains),
        "notes": sum(len(c) for c in chains),
        "by_position": [{"notes": k, "n": by_pos[k][0], "non300": by_pos[k][1],
                         "non300_rate": (by_pos[k][1] / by_pos[k][0]) if by_pos[k][0] else None}
                        for k in ("1-4", "5-8", "9-12", "13+") if k in by_pos],
        "worst": sorted(worst, key=lambda w: -(w["non300"] / w["notes"]))[:5],
    }


def _timing_by_family(results, min_n=MIN_FAMILY_N):
    groups = collections.defaultdict(list)
    for x in results:
        if hit_error(x) is not None:
            groups[family(x)].append(x)
    out = []
    for fam, g in groups.items():
        if len(g) < min_n:
            continue
        errs = [hit_error(x) for x in g]
        nb = sum(1 for x in g if x["result"] != "300")
        out.append({"family": fam, "n": len(g), "bias_ms": st.mean(errs),
                    "p10": sorted(errs)[int(0.1 * len(errs))],
                    "p90": sorted(errs)[min(len(errs) - 1, int(0.9 * len(errs)))],
                    "non300_rate": nb / len(g)})
    return sorted(out, key=lambda d: -abs(d["bias_ms"]))


def _context(results, scale):
    groups = collections.defaultdict(list)
    for x, prev, gap in ((x, p, (x["t"] - p["t"]) if p else None)
                         for x, p in zip(results, [None] + results[:-1])):
        if prev is None:
            continue
        if prev["kind"] == "Spinner":
            key = "after spinner"
        elif prev["kind"] == "Slider":
            dur = (end_time(prev) - prev["t"])
            key = "after long slider" if gap and dur > 0.6 * gap else "after short slider"
        else:
            key = "after circle"
        groups[key].append(x)
    out = []
    for key, g in groups.items():
        nb = sum(1 for x in g if x["result"] != "300")
        errs = [hit_error(x) for x in g if hit_error(x) is not None]
        out.append({"after": key, "n": len(g), "non300_rate": nb / len(g),
                    "bias_ms": st.mean(errs) if errs else None})
    return sorted(out, key=lambda d: -d["n"])


def real_time_rows(results, factor):
    """Copy the rows into the player's time base (``factor`` = mod / calibrated).

    Rows come out of the pipeline in calibrated time; when calibration overrode a
    misleading mod flag that is not the time the player played in, and every ms
    figure here (gaps, stamina, chain gaps) would be off by the same factor.
    """
    if factor == 1.0:
        return results
    out = []
    for x in results:
        y = dict(x)
        y["t"] = x["t"] * factor
        if "end_t" in x:
            y["end_t"] = x["end_t"] * factor
        elif "end" in x:
            y["end"] = x["end"] * factor
        out.append(y)
    return out


def build_profile(results, bm=None, scale=1.0, windows=None, radius=None,
                  time_factor=1.0):
    """The ``profile`` block for the metrics JSON (see the module docstring)."""
    results = real_time_rows(results, time_factor)
    if windows:
        windows = {k: v * time_factor for k, v in windows.items()}
    return {
        "rate": _rate(results, windows),
        "composition": _family_rows(results, radius=radius),
        "sliders": _sliders(bm, scale) if bm is not None else {"n": 0},
        "stamina": _stamina(results),
        "chains": _chains(results),
        "timing_by_family": _timing_by_family(results),
        "context": _context(results, scale),
    }


def primary_target(profile, total_objects, min_n=20, min_factor=1.5):
    """The family that deserves attention: enough objects, worst hit rate.

    Absolute miss counts pick whatever is most numerous; a family is only a
    target when it is populated (``min_n``) and clearly worse than the play as a
    whole (``min_factor``).
    """
    # a 60-second map cannot field 20-object families: scale the gate down
    gate = min(min_n, max(8.0, 0.03 * total_objects))
    fams = [f for f in profile.get("composition", []) if f["n"] >= gate]
    if not fams:
        return None
    total = sum(f["n"] for f in fams)
    overall = sum(f["non300"] for f in fams) / max(1, total)
    worst = max(fams, key=lambda f: f["non300_rate"])
    if worst["non300_rate"] > 0 and overall > 0 and \
            worst["non300_rate"] >= min_factor * overall:
        return worst
    return None
