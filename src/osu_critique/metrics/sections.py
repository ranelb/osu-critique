"""Spatial (region) and temporal (quarter) breakdowns."""
from __future__ import annotations

import numpy as np


def region_stats(results):
    """Miss/aim stats per screen quadrant (512x384 playfield)."""
    regions = {"TL": {"n": 0, "miss": 0, "aims": []},
               "TR": {"n": 0, "miss": 0, "aims": []},
               "BL": {"n": 0, "miss": 0, "aims": []},
               "BR": {"n": 0, "miss": 0, "aims": []}}
    for x in results:
        q = ("T" if x["y"] < 192 else "B") + ("L" if x["x"] < 256 else "R")
        d = regions[q]
        d["n"] += 1
        if x["result"] == "miss":
            d["miss"] += 1
        if x["aim"] is not None:
            d["aims"].append(x["aim"])
    return regions


def quarter_stats(results):
    """Miss/error stats over four equal time quarters."""
    t0, t1 = results[0]["t"], results[-1]["t"]
    span = t1 - t0
    quarters = []
    for k in range(4):
        a, b = t0 + k * span / 4, t0 + (k + 1) * span / 4
        sel = [x for x in results if a <= x["t"] < b]
        qerr = [x["error"] for x in sel if x["error"] is not None]
        qmiss = sum(1 for x in sel if x["result"] == "miss")
        quarters.append({"range": [a, b], "n": len(sel), "miss": qmiss,
                         "mean_err": float(np.mean(qerr)) if qerr else None,
                         "std_err": float(np.std(qerr)) if qerr else None})
    return quarters
