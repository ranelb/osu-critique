"""Spacing-based pattern classification (dense / stream / jump / bigjump)."""
from __future__ import annotations

import math


def bucket(spacing_r):
    if spacing_r is None:
        return "first"
    if spacing_r <= 2.0:
        return "dense"
    if spacing_r <= 4.0:
        return "stream"
    if spacing_r <= 7.0:
        return "jump"
    return "bigjump"


def add_pattern_labels(results, radius):
    """Annotate each result with spacing_r and pattern.

    Spacing is measured from the **previous object's end** (a slider's tail,
    repeats folded back) to this object's head, not from head to head. On this
    corpus 34% of slider-to-next pairs differ by more than 2 circle radii
    between the two readings; the head-to-head version buckets a slider-heavy
    map as if the player never travelled the body.
    """
    for i, x in enumerate(results):
        if i == 0:
            x["spacing_r"] = None
        else:
            p = results[i - 1]
            px = p.get("end_x", p["x"])
            py = p.get("end_y", p["y"])
            x["spacing_r"] = math.hypot(x["x"] - px, x["y"] - py) / radius
        x["pattern"] = bucket(x["spacing_r"])
    return results


def pattern_stats(results):
    """Per-pattern counts, misses and error lists."""
    patterns = {}
    for x in results:
        p = x["pattern"]
        d = patterns.setdefault(p, {"n": 0, "miss": 0, "errs": []})
        d["n"] += 1
        if x["result"] == "miss":
            d["miss"] += 1
        elif x["error"] is not None:
            d["errs"].append(x["error"])
    return patterns
