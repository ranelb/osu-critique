#!/usr/bin/env python3
"""Score the geometric classifier against ``*.labels.json`` files.

Usage:
    python scripts/eval_patterns.py [--slider-tails|--no-slider-tails] [DIR_OR_MAP.osu ...]
    # default dir: tests/fixtures/patterns; the flag overrides geometry.SLIDER_TAILS_DEFAULT

A label file lists blocks ``{"shape", "dir", "t0", "t1"}`` in map ms. A block is
**found** when a predicted segment of the same shape overlaps it by at least
``MIN_IOU`` in time. It is **mislabelled** when something overlaps but under a
different shape, and **missed** when nothing overlaps. A predicted segment that
overlaps no labelled block by at least ``FP_OVERLAP`` of its own length is a
**false positive** -- in junk, that is the number that must stay near zero.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from osu_critique.io.beatmap import build_objects, circle_radius, load_beatmap  # noqa: E402
from osu_critique.metrics import geometry  # noqa: E402

MIN_IOU = 0.5
FP_OVERLAP = 0.5


def _iou(a0, a1, b0, b1):
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = (a1 - a0) + (b1 - b0) - inter
    return inter / union if union > 0 else 0.0


def _overlap_of(seg, blk):
    """Share of the *segment* that lies inside the block."""
    inter = max(0.0, min(seg["t1"], blk["t1"]) - max(seg["t0"], blk["t0"]))
    span = seg["t1"] - seg["t0"]
    return inter / span if span > 0 else 0.0


def score(segs, labels):
    blocks = labels["blocks"]
    result = {"found": [], "mislabelled": [], "missed": [], "false_positive": [],
              "wrong_dir": []}
    for blk in blocks:
        same = [s for s in segs if s["shape"] == blk["shape"]
                and _iou(s["t0"], s["t1"], blk["t0"], blk["t1"]) >= MIN_IOU]
        if same:
            result["found"].append(blk)
            seg = max(same, key=lambda s: _iou(s["t0"], s["t1"], blk["t0"], blk["t1"]))
            if blk.get("dir") and seg.get("dir") and blk["dir"] != seg["dir"]:
                result["wrong_dir"].append((blk, seg["dir"]))
            continue
        other = [s for s in segs
                 if _iou(s["t0"], s["t1"], blk["t0"], blk["t1"]) >= MIN_IOU]
        if other:
            result["mislabelled"].append((blk, sorted({s["shape"] for s in other})))
        else:
            result["missed"].append(blk)
    for s in segs:
        if not any(_overlap_of(s, b) >= FP_OVERLAP for b in blocks):
            result["false_positive"].append(s)
    return result


def run(map_path, verbose=True, slider_tails=None):
    map_path = Path(map_path)
    labels = json.loads(map_path.with_suffix(".labels.json").read_text())
    bm = load_beatmap(str(map_path))
    objs = build_objects(bm, 1.0)
    radius = circle_radius(bm.cs())
    kw = {} if slider_tails is None else {"slider_tails": slider_tails}
    segs = geometry.classify(objs, radius, labels.get("beat_ms"), **kw)
    res = score(segs, labels)
    n = len(labels["blocks"])
    summary = geometry.summarize(segs, len(objs))
    if verbose:
        print(f"{map_path.stem}: {len(res['found'])}/{n} found, "
              f"{len(res['mislabelled'])} mislabelled, {len(res['missed'])} missed, "
              f"{len(res['false_positive'])} false-positive segments, "
              f"{len(res['wrong_dir'])} wrong winding "
              f"(coverage {summary['coverage']:.0%})")
        for blk, got in res["mislabelled"]:
            print(f"    mislabelled  {blk['shape']:15s} {blk['t0']:>7}-{blk['t1']:<7} -> {', '.join(got)}")
        for blk in res["missed"]:
            print(f"    missed       {blk['shape']:15s} {blk['t0']:>7}-{blk['t1']:<7}")
        for s in res["false_positive"]:
            print(f"    false pos    {s['shape']:15s} {s['t0']:>7.0f}-{s['t1']:<7.0f} n={s['n']}")
        for blk, got in res["wrong_dir"]:
            print(f"    wrong dir    {blk['shape']:15s} {blk['t0']:>7}-{blk['t1']:<7} said {got}")
    return res, segs, labels


def main(argv):
    flag = None
    if "--slider-tails" in argv:
        flag = True
    if "--no-slider-tails" in argv:
        flag = False
    argv = [a for a in argv if not a.startswith("--") ]
    targets = [Path(a) for a in argv] or [ROOT / "tests" / "fixtures" / "patterns"]
    maps = []
    for t in targets:
        maps += sorted(t.glob("*.osu")) if t.is_dir() else [t]
    for m in maps:
        if m.with_suffix(".labels.json").exists():
            run(m, slider_tails=flag)


if __name__ == "__main__":
    main(sys.argv[1:])
