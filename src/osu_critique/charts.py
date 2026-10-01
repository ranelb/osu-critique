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


def render_aim_charts(rows, radius, window_ms, tag, outdir, title=""):
    """Write ``{outdir}/{tag}_aim.png``: the six-panel cursor-arrival autopsy.

    Panels: (a) the aim ceiling, (b) arrival timing, (c) the along/lateral target
    frame, (d) drift through the play, (e) where on the playfield, (f) "there,
    just not then". ``rows`` is ``metrics.aim.cursor_rows`` output.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    d = np.array([r["d"] for r in rows])
    dmin = np.array([r["dmin"] for r in rows])
    peak = np.array([r["peak_off"] for r in rows])
    along = np.array([np.nan if r["along"] is None else r["along"] for r in rows])
    lat = np.array([np.nan if r["lat"] is None else r["lat"] for r in rows])
    have_axis = ~np.isnan(along)
    sp = np.array([r["speed"] if r["speed"] is not None else np.nan for r in rows])
    t = np.array([r["t"] for r in rows])
    ok = ~np.isnan(sp)
    band = (dmin <= 1.0) & (d > 1.0)
    w = window_ms

    fig, ax = plt.subplots(2, 3, figsize=(19, 10.5))
    a = ax[0][0]
    a.scatter(sp[ok], d[ok], s=9, alpha=0.28, color="#3b6ea5")
    edges = np.array([0, .5, 1, 1.5, 2, 3, 6])
    ctr, med, p90 = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        s = ok & (sp >= lo) & (sp < hi)
        if s.sum() >= 5:
            ctr.append((lo + hi) / 2)
            med.append(np.median(d[s]))
            p90.append(np.percentile(d[s], 90))
    a.plot(ctr, med, "-o", color="#10305a", lw=2.4, label="median")
    a.plot(ctr, p90, "--s", color="#c0392b", lw=1.8, label="p90")
    a.axhline(1.0, color="#e02020", lw=1.6)
    a.set_xlabel("required cursor speed to this note (px/ms)")
    a.set_ylabel("cursor distance from centre at the note (radii)")
    a.set_title("(a) the aim ceiling"); a.legend(fontsize=9); a.set_ylim(0, 3.2)

    a = ax[0][1]
    a.hist(peak, bins=np.arange(-w, w + 10, 10), color="#7a9c7a")
    a.axvline(0, color="#333333", lw=2)
    for x in (-20, 20):
        a.axvline(x, color="#e02020", lw=1.4, ls="--")
    a.set_xlabel("when the cursor is closest to the object (ms vs the note)")
    a.set_ylabel("objects")
    a.set_title(f"(b) arrival timing: median {np.median(peak):+.0f} ms\n"
                f"{100 * np.mean(peak > 20):.0f}% peak late, "
                f"{100 * np.mean(peak < -20):.0f}% early")

    a = ax[0][2]
    sc = a.scatter(along[have_axis] * radius, lat[have_axis] * radius,
                   c=sp[have_axis], cmap="plasma", s=10, alpha=0.7)
    a.add_patch(plt.Circle((0, 0), radius, fill=False, color="#e02020", lw=2))
    a.axvline(0, color="#888888", lw=0.8); a.axhline(0, color="#888888", lw=0.8)
    a.set_xlabel("error along the travel axis (px): negative = short")
    a.set_ylabel("lateral error (px)")
    a.set_title(f"(c) target frame: {100 * np.mean(along[have_axis] < 0):.0f}% short, "
                f"{100 * np.mean(along[have_axis] > 0):.0f}% past")
    a.set_aspect("equal"); a.set_xlim(-160, 160); a.set_ylim(-160, 160)
    plt.colorbar(sc, ax=a, label="required speed (px/ms)")

    a = ax[1][0]
    t0, t1 = float(t[0]), float(t[-1])
    xs, m_, p9, ins = [], [], [], []
    for k in range(max(1, int((t1 - t0) / 10000))):
        lo, hi = t0 + k * 10000, t0 + (k + 1) * 10000
        s = (t >= lo) & (t < hi)
        if s.sum() >= 5:
            xs.append((lo + hi) / 2000 - t0 / 2000)
            m_.append(d[s].mean())
            p9.append(np.percentile(d[s], 90))
            ins.append(100 * np.mean(d[s] <= 1))
    a.plot(xs, m_, "-o", color="#10305a", label="mean distance at the note")
    a.plot(xs, p9, "--", color="#c0392b", label="p90")
    a.axhline(1.0, color="#e02020", lw=1.6)
    a2 = a.twinx()
    a2.plot(xs, ins, ":", color="#2e8b57", lw=2, label="% inside")
    a2.set_ylabel("% of notes with the cursor inside", color="#2e8b57")
    a2.set_ylim(0, 100)
    a.set_xlabel("map time (s)"); a.set_ylabel("distance at the note (radii)")
    a.set_title("(d) drift through the play"); a.legend(fontsize=9, loc="upper left")

    a = ax[1][1]
    sc = a.scatter([r["x"] for r in rows], [r["y"] for r in rows],
                   c=np.clip(d, 0, 2.5), cmap="RdYlGn_r", s=14, alpha=0.85)
    a.set_xlim(0, 512); a.set_ylim(384, 0); a.set_aspect("equal")
    a.set_title("(e) where on the playfield")
    plt.colorbar(sc, ax=a, label="distance (radii)")

    a = ax[1][2]
    mm = dmin <= 1.0
    a.scatter(dmin[mm], d[mm], s=9, alpha=0.5, color="#3b6ea5",
              label="inside at some point")
    a.scatter(dmin[~mm], d[~mm], s=14, alpha=0.9, color="#e02020",
              label="never inside")
    a.scatter(dmin[band], d[band], s=12, alpha=0.55, color="#f0a020",
              label=f"inside, not at the note ({int(band.sum())})")
    a.plot([0, 3], [0, 3], color="#999999", lw=1, ls=":")
    a.axhline(1.0, color="#e02020", lw=1.4); a.axvline(1.0, color="#e02020", lw=1.4)
    a.set_xlabel(f"best approach within +/-{w:.0f} ms (radii)")
    a.set_ylabel("distance at the note instant (radii)")
    a.set_title(f"(f) {100 * band.mean():.0f}% of notes: there, just not then")
    a.legend(fontsize=8); a.set_xlim(0, 3); a.set_ylim(0, 4.5)

    plt.suptitle(f"{title} - cursor arrival ({len(rows)} objects)", fontsize=13)
    plt.tight_layout(rect=(0, 0, 1, 0.965))
    path = os.path.join(outdir, f"{tag}_aim.png")
    plt.savefig(path, dpi=105)
    plt.close()
    return path
