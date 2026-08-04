"""Chart rendering (matplotlib, lazily imported)."""
from __future__ import annotations

import os

import numpy as np


def render_charts(results, errs, aims, w300, w100, w50, ur, radius,
                  tag, outdir):
    """Write ``{outdir}/{tag}_charts.png``: hit-error histogram, timeline,
    spatial result map, aim-error histogram."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    hits = [x for x in results if x["result"] != "miss"]

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    # 1 hit error histogram
    ax = axes[0][0]
    ax.hist(errs, bins=40, color="#4a9", alpha=0.8)
    for w, c in [(w300, "#8f8"), (w100, "#ff8"), (w50, "#fa8")]:
        ax.axvline(w, color=c, ls="--", lw=1)
        ax.axvline(-w, color=c, ls="--", lw=1)
    ax.axvline(0, color="#fff", lw=1.5)
    ax.set_title(f"Hit error (ms)  mean={float(np.mean(errs)):.1f} "
                 f"std={float(np.std(errs)):.1f} UR={ur:.1f}")
    ax.set_xlabel("early < 0 | late > 0")

    # 2 timeline
    ax = axes[0][1]
    ts = [x["t"] for x in hits]
    ax.scatter(ts, [x["error"] for x in hits], s=6, alpha=0.4, c="#6cf")
    misses = [x for x in results if x["result"] == "miss"]
    ax.scatter([x["t"] for x in misses], [w50 + 5] * len(misses),
               c="r", marker="x", label="misses")
    if len(ts) > 30:
        ts_a, err_a = np.array(ts), np.array([x["error"] for x in hits])
        k = max(5, len(ts_a) // 50)
        ker = np.ones(k) / k
        ax.plot(np.convolve(ts_a, ker, "same"), np.convolve(err_a, ker, "same"),
                c="#f80", lw=2)
    ax.axhline(0, color="#888", lw=1)
    ax.set_title("Hit error over time (orange = rolling mean, x = miss)")
    ax.set_ylabel("ms")

    # 3 spatial
    ax = axes[1][0]
    for x in results:
        c = {"300": "#3f3", "100": "#ff3", "50": "#fa3", "miss": "#f33"}[x["result"]]
        ax.scatter(x["x"], x["y"], s=6, c=c, alpha=0.7)
    ax.set_xlim(0, 512)
    ax.set_ylim(384, 0)
    ax.set_title("All objects colored by result (g/y/o/red = 300/100/50/miss)")

    # 4 aim error hist
    ax = axes[1][1]
    ax.hist(aims / radius, bins=40, color="#c9a", alpha=0.8)
    ax.axvline(1, color="#fff", ls="--", lw=1, label="1 circle radius")
    ax.set_title(f"Aim error (circle radii) mean={float(np.mean(aims)) / radius:.2f}  |  r={radius:.0f}px")
    ax.set_xlabel("distance from object center at keypress")
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, f"{tag}_charts.png"), dpi=110)
    plt.close()
