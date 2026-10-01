"""Rolling baselines: how does this run compare with the ones already stored?

The report's verdicts used to be frozen strings ("UR < 120 = excellent"), which
say nothing about *this* player at *this* difficulty. Every run writes a metrics
file, and the `attempts` layer already groups them, so the honest comparison is
against the player's own history — difficulty-normalised so that maps of
different shapes are comparable:

``timing_spread``
    UR as a percentage of the 300-window (already normalised by OD and by DT/HT):
    "a 140 UR on OD 9.2" and "a 140 UR on OD 7" are not the same achievement.
``miss_rate``
    misses per 100 objects, so a 1000-object map does not look worse than a
    200-object one for the same play quality.
``aim_at_demand``
    the mean distance at the note in the 1.0-1.5 px/ms required-speed band: the
    same *demand* on every map, instead of an average over whatever the map
    happened to contain.

Each metric gets a percentile against the stored runs ("better than 78 % of your
42 stored runs"), and a verdict sentence built from it. With fewer than
``MIN_RUNS`` comparable runs the block says so and reports nothing: a percentile
over five runs is not a baseline.
"""
from __future__ import annotations

MIN_RUNS = 8                # below this, "your history" is not a baseline
AIM_BAND = (0.5, 2.0)       # the required-speed band aim is compared at, px/ms
                            # (the "usable range" the author's own data ends at)

METRICS = ("timing_spread", "miss_rate", "aim_at_demand")


def _timing_spread(m):
    """UR as a % of the 300-window (OD- and mod-normalised)."""
    v = m.get("ur_pct_of_300_window")
    if v is None:
        ur, w = m.get("ur"), (m.get("windows_ms") or {}).get("300")
        v = (ur / 10.0 / w * 100.0) if (ur is not None and w) else None
    return v


def _miss_rate(m):
    det = m.get("counts_detected") or {}
    n = m.get("n_objects")
    if not n or det.get("miss") is None:
        return None
    return 100.0 * det["miss"] / n


def _aim_at_demand(m):
    """Mean distance at the note pooled over the reference demand band.

    Pooling the ceiling bins that fall inside ``AIM_BAND`` (weighted by n) keeps
    the demand identical across maps - the point of the normalisation - while
    surviving the small maps where a single bin has too few objects to be
    reported at all.
    """
    lo, hi = AIM_BAND
    num = den = 0.0
    for b in ((m.get("aim_mode") or {}).get("ceiling") or []):
        if b.get("mean_r") is None or b["v_lo"] < lo or b["v_hi"] > hi:
            continue
        num += b["mean_r"] * b["n"]
        den += b["n"]
    return (num / den) if den else None


NORMALISERS = {"timing_spread": _timing_spread,
               "miss_rate": _miss_rate,
               "aim_at_demand": _aim_at_demand}

BETTER_IS_LOWER = {"timing_spread": True, "miss_rate": True, "aim_at_demand": True}

LABELS = {
    "timing_spread": ("timing spread (UR as % of the 300-window)", "%"),
    "miss_rate": ("miss rate (misses per 100 objects)", "%"),
    "aim_at_demand": (f"aim at {AIM_BAND[0]:.1f}-{AIM_BAND[1]:.1f} px/ms demand (radii)", "r"),
}


def normalise(metrics):
    return {k: fn(metrics) for k, fn in NORMALISERS.items()}


def better_than_pct(value, values, lower_is_better=True):
    """Share of stored runs this one beats (0-100)."""
    vs = [v for v in values if v is not None]
    if not vs or value is None:
        return None
    worse = sum(1 for v in vs if (v > value if lower_is_better else v < value))
    return 100.0 * worse / len(vs)


def _ident(m):
    return (m.get("replay_md5") or m.get("tag"), m.get("played_at"))


def history_report(metrics, runs, min_runs=MIN_RUNS):
    """Compare one run against the stored ones. ``runs`` is [(name, metrics)]."""
    me = _ident(metrics)
    others = [m for _n, m in runs if _ident(m) != me]
    block = {"n_runs": len(others), "min_runs": min_runs, "metrics": {}}
    for key in METRICS:
        value = NORMALISERS[key](metrics)
        values = [NORMALISERS[key](m) for m in others]
        values = [v for v in values if v is not None]
        if value is None or len(values) < min_runs:
            block["metrics"][key] = {"value": value, "n": len(values),
                                     "enough": False}
            continue
        block["metrics"][key] = {
            "value": value,
            "n": len(values),
            "enough": True,
            "better_than_pct": better_than_pct(value, values, BETTER_IS_LOWER[key]),
            "median": float(sorted(values)[len(values) // 2]),
            "p10": float(sorted(values)[max(0, int(0.10 * len(values)))]),
            "p90": float(sorted(values)[min(len(values) - 1, int(0.90 * len(values)))]),
        }
    block["verdict"] = _verdict(block)
    return block


def _verdict(block):
    ready = {k: v for k, v in block["metrics"].items() if v.get("enough")}
    if not ready:
        return (f"not enough stored runs to compare ({block['n_runs']} stored, "
                f"{block['min_runs']} needed)")
    bits = []
    for k, v in ready.items():
        label, _unit = LABELS[k]
        bits.append(f"{label}: better than {v['better_than_pct']:.0f}% of "
                    f"{v['n']} runs (median {v['median']:.1f})")
    return "; ".join(bits) + "."


def describe(block):
    """Human-readable lines for the comparison block."""
    lines = [f"AGAINST YOUR HISTORY ({block['n_runs']} stored runs, "
             f"min {block['min_runs']})"]
    for key, v in block["metrics"].items():
        label, unit = LABELS[key]
        if not v.get("enough"):
            lines.append(f"  {label}: {v['value'] if v['value'] is not None else 'n/a'}"
                         f" — only {v['n']} comparable run(s)")
            continue
        lines.append(f"  {label}: {v['value']:.2f}{unit} — better than "
                     f"{v['better_than_pct']:.0f}% of {v['n']} runs "
                     f"(median {v['median']:.2f}, p10 {v['p10']:.2f}, p90 {v['p90']:.2f})")
    lines.append(f"  verdict: {block['verdict']}")
    return lines
