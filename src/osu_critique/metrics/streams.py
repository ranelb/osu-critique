"""Stream segment detection: runs of consecutive stream/dense circles."""
from __future__ import annotations

import numpy as np


def stream_stats(results):
    """Runs of >=4 consecutive circles with stream/dense spacing, with per-segment
    timing (std/UR) and alternation ratio (same-finger double-taps under pressure)."""
    streams, run = [], []
    for x in results:
        if x["kind"] == "Circle" and x["pattern"] in ("stream", "dense"):
            run.append(x)
        else:
            if len(run) >= 4:
                streams.append(run)
            run = []
    if len(run) >= 4:
        streams.append(run)

    out = []
    for s in streams:
        seg_errs = [x["error"] for x in s if x["error"] is not None]
        keys = [x["key"] for x in s if x["key"]]
        same_key = sum(1 for a, b in zip(keys, keys[1:]) if a == b)
        out.append({
            "t_start": round(s[0]["t"], 1), "t_end": round(s[-1]["t"], 1),
            "n": len(s),
            "miss": sum(1 for x in s if x["result"] == "miss"),
            "mean_err": float(np.mean(seg_errs)) if seg_errs else None,
            "std_err": float(np.std(seg_errs)) if seg_errs else None,
            "alt_ratio": 1 - same_key / max(1, len(keys) - 1),
            "key_pattern": "".join(keys)[:60],
        })
    return out
