#!/usr/bin/env python3
"""Render label_sheet windows as PNG contact sheets (for a model to read), plus a data file.

    python scripts/render_windows.py OUTDIR MAP.osu [...] [--per-map 5] [--seed 2] [--per-sheet 6]

Writes OUTDIR/sheet_N.png and OUTDIR/windows.json (same entries as the labeler, ``src`` kept
there only). Panels show only ids, object numbers, true radii, arrows and slider paths.
"""
import argparse, json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import label_sheet as L
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle


def panel(ax, w):
    r = w["r"]
    rows = w["rows"]
    inside = [x for x in rows if w["i0"] <= x["i"] <= w["i1"]]
    for x in rows:
        a = 1.0 if w["i0"] <= x["i"] <= w["i1"] else 0.3
        if x["p"]:
            ax.plot([p[0] for p in x["p"]], [p[1] for p in x["p"]], color="#888", lw=2, alpha=a)
        ax.add_patch(Circle((x["x"], x["y"]), r, fill=False, ec="#2a6df4" if a == 1 else "#aaa", lw=1.2))
    for p, q in zip(rows, rows[1:]):
        ax.annotate("", xy=(q["x"], q["y"]), xytext=(p["ex"], p["ey"]),
                    arrowprops=dict(arrowstyle="->", color="#d33", lw=0.9, alpha=0.7))
    seen = {}
    for x in rows:
        seen.setdefault((round(x["x"]), round(x["y"])), []).append(x["i"] - w["i0"] + 1)
    for (px, py), ns in seen.items():
        ax.text(px, py, ",".join(map(str, ns)), ha="center", va="center", fontsize=8)
    xs = [x["x"] for x in rows] + [x["ex"] for x in rows]
    ys = [x["y"] for x in rows] + [x["ey"] for x in rows]
    pad = 2 * r
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(max(ys) + pad, min(ys) - pad)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    dt = inside[-1]["t"] - inside[0]["t"]
    ax.set_title(f"#{w['id']}  {len(inside)} obj  {dt} ms  (1 = first, grey = context)", fontsize=9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("maps", nargs="+")
    ap.add_argument("--per-map", type=int, default=5)
    ap.add_argument("--seed", type=int, default=2)
    ap.add_argument("--per-sheet", type=int, default=6)
    a = ap.parse_args()
    wins = L.build(a.maps, a.per_map, a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "windows.json").write_text(json.dumps(wins))
    for s in range(0, len(wins), a.per_sheet):
        chunk = wins[s:s + a.per_sheet]
        fig, axs = plt.subplots(2, 3, figsize=(15, 10))
        for ax in axs.flat:
            ax.axis("off")
        for ax, w in zip(axs.flat, chunk):
            ax.axis("on"); panel(ax, w)
        fig.tight_layout()
        fig.savefig(out / f"sheet_{s // a.per_sheet + 1}.png", dpi=80)
        plt.close(fig)
    print(len(wins), "windows ->", out)


if __name__ == "__main__":
    main()
