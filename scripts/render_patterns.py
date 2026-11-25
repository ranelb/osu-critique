#!/usr/bin/env python3
"""Draw what the geometric classifier found, so a person can say if it is right.

Usage:
    python scripts/render_patterns.py MAP.osu [OUT.png] [--per-shape N] [--shapes a,b,c]

One panel per detected segment (up to N per shape, spread across the map): the
notes in the segment numbered and coloured, three notes of context either side in
grey, the real circle size, and a caption with the shape, winding, time, note
count and gap. Needs matplotlib (the ``[charts]`` extra).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle  # noqa: E402

from osu_critique.io.beatmap import build_objects, circle_radius, load_beatmap  # noqa: E402
from osu_critique.metrics import geometry  # noqa: E402

COLORS = {"triangle": "#e4572e", "square": "#17bebb", "rectangle": "#17bebb",
          "quad": "#17bebb", "pentagon": "#9b5de5", "hexagon": "#9b5de5",
          "polygon": "#9b5de5", "star": "#6a4c93", "back_and_forth": "#f3a712", "zigzag": "#2e86ab",
          "circle": "#2fbf71", "arc": "#7bc950", "line": "#d1495b", "stack": "#8d6a9f"}
CONTEXT = 3


def _clock(ms):
    s = ms / 1000.0
    return f"{int(s // 60)}:{s % 60:04.1f}"


def pick(segs, per_shape, shapes=None):
    by = {}
    for s in segs:
        if shapes and s["shape"] not in shapes:
            continue
        by.setdefault(s["shape"], []).append(s)
    chosen = []
    for shape in sorted(by, key=lambda k: geometry.PRIORITY[k]):
        group = by[shape]
        if len(group) <= per_shape:
            chosen += group
        else:                                   # evenly spread, not just the first few
            step = (len(group) - 1) / (per_shape - 1) if per_shape > 1 else 0
            chosen += [group[round(i * step)] for i in range(per_shape)]
    return chosen


def render(map_path, out_png, per_shape=4, shapes=None, cols=4):
    bm = load_beatmap(str(map_path))
    objs = build_objects(bm, 1.0)
    radius = circle_radius(bm.cs())
    segs = geometry.classify(objs, radius)
    summary = geometry.summarize(segs, len(objs))
    chosen = pick(segs, per_shape, shapes)
    if not chosen:
        print("nothing to draw")
        return summary
    rows = (len(chosen) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.6, rows * 3.0), squeeze=False)
    for ax in axes.flat:
        ax.axis("off")
    for ax, seg in zip(axes.flat, chosen):
        ax.axis("on")
        lo, hi = max(0, seg["start"] - CONTEXT), min(len(objs) - 1, seg["end"] + CONTEXT)
        color = COLORS.get(seg["shape"], "#444")
        ctx = [i for i in range(lo, hi + 1) if not seg["start"] <= i <= seg["end"]]
        ax.plot([objs[i]["x"] for i in range(lo, hi + 1)],
                [objs[i]["y"] for i in range(lo, hi + 1)], "-", color="#bbb", lw=1, zorder=1)
        for i in ctx:
            ax.add_patch(Circle((objs[i]["x"], objs[i]["y"]), radius, fc="#eee", ec="#aaa", lw=.6, zorder=2))
        xs = [objs[i]["x"] for i in range(seg["start"], seg["end"] + 1)]
        ys = [objs[i]["y"] for i in range(seg["start"], seg["end"] + 1)]
        ax.plot(xs, ys, "-", color=color, lw=1.6, zorder=3)
        for k, i in enumerate(range(seg["start"], seg["end"] + 1)):
            o = objs[i]
            ax.add_patch(Circle((o["x"], o["y"]), radius, fc=color, alpha=.22, ec=color, lw=.8,
                                ls="-" if o.get("kind") != "Slider" else "--", zorder=4))
            ax.text(o["x"], o["y"], str(k + 1), ha="center", va="center", fontsize=6.5, zorder=5)
        ax.set_xlim(-30, 542)
        ax.set_ylim(414, -30)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        who = seg["shape"] + (f" {seg['dir']}" if seg.get("dir") else "")
        gap = f"{seg['rate_ms']:.0f}ms" if seg["rate_ms"] else "-"
        sl = " +sliders" if seg["has_sliders"] else ""
        ax.set_title(f"{who}  {_clock(seg['t0'])}  n={seg['n']}  gap {gap}  {seg['spacing_r']:.1f}r{sl}",
                     fontsize=8, color=color)
    cov = summary["coverage"]
    fig.suptitle(f"{bm.artist} - {bm.title} [{bm.version}]   {len(objs)} notes, "
                 f"{len(segs)} segments, {cov:.0%} of notes labelled", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, .97))
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("map")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--per-shape", type=int, default=4)
    ap.add_argument("--shapes", default="")
    a = ap.parse_args()
    out = a.out or str(Path(a.map).with_suffix(".patterns.png"))
    render(a.map, out, a.per_shape, set(filter(None, a.shapes.split(","))) or None)
    print(out)


if __name__ == "__main__":
    main()
