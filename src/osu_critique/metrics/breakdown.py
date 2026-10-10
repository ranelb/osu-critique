"""How a play breaks down: the mechanism underneath the misses.

``streams``, ``patterns`` and the miss autopsy say *where* a play fails. This
block says *how*: the required cursor speed at each object, the miss rate per
speed bin (the speed cliff), sharp-turn x spacing buckets, runs of consecutive
misses (cascades) and the worst ramp (the densest cluster of misses).

The speed is recomputed from geometry -- ``dist(prev -> this) / dt`` -- instead
of read from ``objects[].cursor_speed``, because that field is null on no-press
misses and binning on it silently hides exactly the misses this block is about.

Pure computation, no I/O and no plotting: the skill renders the figure from this
block, the CLI prints it and the report section cites it.

    breakdown.build(objects) -> {
        "speed_bins":  [{"label", "lo", "hi", "n", "miss", "rate"}, ...],
        "knee":        hi of the fastest bin still under 10% miss (or None),
        "cliff":       lo of the first bin at/above 25% miss (or None),
        "reversal":    {name: {"n", "miss", "rate"}},
        "cascades":    [{"start_i", "end_i", "n", "t0", "t1"}, ...],
        "ramp":        {"t0","t1","n","miss","spacing","speed","mid_t"} | None,
    }
"""
from __future__ import annotations

import math

SPEED_BINS = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, float("inf")]
REVERSAL_DEG = 150.0
RAMP_WIN = 28
MAX_GAP_MS = 1500.0


def _num(x, k):
    v = x.get(k)
    return v if isinstance(v, (int, float)) else None


def required_speeds(objs, max_gap_ms=MAX_GAP_MS):
    """``{i: px/ms}`` needed to travel from the previous object to object ``i``.

    Gaps longer than ``max_gap_ms`` are breaks, not travel, and are skipped;
    the first object has no predecessor and no entry.
    """
    req = {}
    for a, b in zip(objs, objs[1:]):
        dt = b["t"] - a["t"]
        if dt <= 0 or dt > max_gap_ms:
            continue
        req[b["i"]] = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) / dt
    return req


def _bin_label(lo, hi):
    return f"{lo:g}+" if hi == float("inf") else f"{lo:g}-{hi:g}"


def miss_rate_table(objs, req, bins=SPEED_BINS):
    """Miss rate per required-speed bin (runs of consecutive objects)."""
    rows = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        xs = [x for x in objs if x["i"] in req and lo <= req[x["i"]] < hi]
        if not xs:
            continue
        miss = sum(1 for x in xs if x["result"] == "miss")
        rows.append({"label": _bin_label(lo, hi), "lo": lo, "hi": hi,
                     "n": len(xs), "miss": miss, "rate": 100.0 * miss / len(xs)})
    return rows


def cliff_knee(rows, under=10.0, blowup=25.0, min_safe=10, min_blow=5):
    """The two edges of the speed cliff: the last safe bin and the first bad one.

    Returns ``(knee, cliff)``: ``knee`` is the upper edge of the fastest bin
    still under ``under`` % miss (n >= ``min_safe``), ``cliff`` the lower edge of
    the first bin at/above ``blowup`` % (n >= ``min_blow``). Either may be None.
    """
    knee = cliff = None
    for r in rows:
        if r["n"] >= min_safe and r["rate"] < under:
            knee = r["hi"]
        if cliff is None and r["n"] >= min_blow and r["rate"] >= blowup:
            cliff = r["lo"]
    return knee, cliff


def reversal_table(objs):
    """Miss rate for sharp turns, split by whether the jump is wide (>= 6r)."""
    defs = (
        ("sharp>=150deg, spacing>=6r",
         lambda x: (_num(x, "angle_deg") or 0) >= REVERSAL_DEG
         and (_num(x, "spacing_r") or 0) >= 6.0),
        ("sharp>=150deg, spacing<6r",
         lambda x: (_num(x, "angle_deg") or 0) >= REVERSAL_DEG
         and _num(x, "spacing_r") is not None and (_num(x, "spacing_r") or 0) < 6.0),
        ("flow<60deg, spacing>=6r",
         lambda x: _num(x, "angle_deg") is not None and x["angle_deg"] < 60.0
         and (_num(x, "spacing_r") or 0) >= 6.0),
    )
    out = {}
    for name, pred in defs:
        xs = [x for x in objs if pred(x)]
        if not xs:
            continue
        miss = sum(1 for x in xs if x["result"] == "miss")
        out[name] = {"n": len(xs), "miss": miss, "rate": 100.0 * miss / len(xs)}
    return out


def cascades(objs, min_len=2):
    """Maximal runs of consecutive-object misses (accumulation, not whiffs)."""
    by_i = {x["i"]: x for x in objs}
    runs, cur = [], []
    for o in objs:
        if o["result"] == "miss":
            if cur and o["i"] != cur[-1] + 1:
                runs.append(cur)
                cur = []
            cur.append(o["i"])
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    out = [{"start_i": r[0], "end_i": r[-1], "n": len(r),
            "t0": by_i[r[0]]["t"] / 1000.0, "t1": by_i[r[-1]]["t"] / 1000.0}
           for r in runs if len(r) >= min_len]
    return sorted(out, key=lambda r: -r["n"])


def pick_ramp(objs, req, win=RAMP_WIN):
    """The ``win`` consecutive travels with the most misses, then the fastest."""
    seq = [x for x in objs if x["i"] in req]
    if len(seq) <= win:
        return seq
    best, best_key = None, None
    for i in range(len(seq) - win + 1):
        chunk = seq[i:i + win]
        miss = sum(1 for x in chunk if x["result"] == "miss")
        fastest = max(req[x["i"]] for x in chunk)
        key = (miss, fastest)
        if best_key is None or key > best_key:
            best_key, best = key, chunk
    return best


def _ramp_summary(ramp, req):
    if not ramp:
        return None
    sp = [v for v in (_num(x, "spacing_r") for x in ramp) if v is not None]
    rs = [req[x["i"]] for x in ramp if x["i"] in req]
    return {
        "t0": ramp[0]["t"] / 1000.0,
        "t1": ramp[-1]["t"] / 1000.0,
        "mid_t": ramp[len(ramp) // 2]["t"] / 1000.0,
        "n": len(ramp),
        "miss": sum(1 for x in ramp if x["result"] == "miss"),
        "spacing": [min(sp), max(sp)] if sp else None,
        "speed": [min(rs), max(rs)] if rs else None,
        "object_ids": [x["i"] for x in ramp],
    }


def build(objs):
    """The full breakdown block for a run's per-object records."""
    req = required_speeds(objs)
    rows = miss_rate_table(objs, req)
    knee, cliff = cliff_knee(rows)
    return {
        "speed_bins": rows,
        "knee": knee,
        "cliff": cliff,
        "reversal": reversal_table(objs),
        "cascades": cascades(objs, min_len=2),
        "ramp": _ramp_summary(pick_ramp(objs, req), req),
    }


def console_lines(block, trust=None):
    """Human-readable lines for the breakdown block (no figures)."""
    if not block:
        return ["(no breakdown computed; analyze without --no-objects)"]
    lines = ["## How it breaks down"]
    if trust is False:
        lines.append("- ! trust=false: numbers are approximate — critique only "
                     "the mechanism, not the exact rate")
    ramp = block.get("ramp") or {}
    cause = "isolated whiffs"
    if block.get("cascades"):
        top = block["cascades"][0]
        cause = f"cascades (worst {top['n']} in a row at t={top['t0']:.0f}s)"
    if block.get("cliff"):
        lines.append(f"- the speed cliff: safe to ~{block.get('knee') or 0:g} px/ms, "
                     f"misses explode past ~{block['cliff']:g} px/ms; failure is {cause}")
    elif block.get("speed_bins"):
        lines.append(f"- no speed cliff in this run; failure is {cause}")
    lines.append("- miss rate by required speed (px/ms):")
    for r in block.get("speed_bins") or []:
        lines.append(f"    {r['label']:>7}  n={r['n']:4d}  miss={r['miss']:3d}  {r['rate']:5.1f}%")
    for k, v in (block.get("reversal") or {}).items():
        lines.append(f"- {k:<26} n={v['n']:4d} miss={v['miss']:3d} {v['rate']:5.1f}%")
    if ramp:
        extra = ""
        if ramp.get("spacing"):
            extra += f"  spacing {ramp['spacing'][0]:.1f}->{ramp['spacing'][1]:.1f}r"
        if ramp.get("speed"):
            extra += f"  required {ramp['speed'][0]:.2f}->{ramp['speed'][1]:.2f} px/ms"
        lines.append(f"- worst ramp t={ramp['t0']:.1f}-{ramp['t1']:.1f}s "
                     f"{ramp['miss']} miss of {ramp['n']}{extra}")
    return lines
