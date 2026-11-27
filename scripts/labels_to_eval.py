#!/usr/bin/env python3
"""Turn the labeler's ``labels.json`` into eval blocks and score the classifier.

Usage:
    python scripts/labels_to_eval.py labels.json MAP.osu [MAP.osu ...] [--write DIR]

Entries come from ``scripts/label_sheet.py`` (``map`` = .osu stem, ``shape``,
``t0``/``t1`` in map ms). Shapes the geometry classifier can name become blocks;
``none`` (nothing there), ``other``, ``unsure`` and the descriptor-only shapes
(wide_jumps, curvy_stream, drifting_polygon) are kept out of the shape score and
reported separately. ``--write DIR`` also writes ``<stem>.labels.json`` files in
the format ``scripts/eval_patterns.py`` reads.

Output: per label, which shapes the classifier predicted over it (overlap share),
a confusion table, and the false-positive rate on windows you marked ``none``.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from osu_critique.io.beatmap import build_objects, circle_radius, load_beatmap  # noqa: E402
from osu_critique.metrics import geometry  # noqa: E402

SKIP = {"other", "unsure"}
DESCRIPTOR_ONLY = {"wide_jumps", "curvy_stream", "drifting_polygon"}


def _share(seg, t0, t1):
    """Share of the labelled span covered by the segment."""
    inter = max(0.0, min(seg["t1"], t1) - max(seg["t0"], t0))
    return inter / (t1 - t0) if t1 > t0 else 0.0


def load(path):
    data = json.loads(Path(path).read_text())
    return data["labels"] if isinstance(data, dict) else data


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("labels")
    ap.add_argument("maps", nargs="+")
    ap.add_argument("--write", metavar="DIR")
    a = ap.parse_args(argv)

    entries = load(a.labels)
    maps = {Path(p).stem: p for p in a.maps}
    by_map = defaultdict(list)
    for e in entries:
        by_map[e["map"]].append(e)
    unknown = sorted(set(by_map) - set(maps))
    if unknown:
        print("no .osu given for:", ", ".join(unknown), file=sys.stderr)

    confusion, fp_none, n_none = Counter(), 0, 0
    for stem, es in by_map.items():
        if stem not in maps:
            continue
        bm = load_beatmap(maps[stem])
        objs = build_objects(bm, 1.0)
        segs = geometry.classify(objs, circle_radius(bm.cs()), None)
        blocks = []
        for e in es:
            shape = e["shape"]
            if shape in SKIP:
                continue
            t0, t1 = e["t0"], e["t1"]
            over = sorted(((_share(s, t0, t1), s["shape"]) for s in segs if _share(s, t0, t1) > 0),
                          reverse=True)
            pred = over[0][1] if over and over[0][0] >= 0.5 else "(unlabelled)"
            if shape == "none":
                n_none += 1
                fp_none += pred != "(unlabelled)"
            confusion[(shape, pred)] += 1
            if shape not in DESCRIPTOR_ONLY | {"none"}:
                blocks.append({"shape": shape, "dir": None, "t0": t0, "t1": t1})
        if a.write and blocks:
            out = Path(a.write)
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{stem}.labels.json").write_text(
                json.dumps({"map": stem, "blocks": blocks}, indent=2))

    print(f"{'you said':<18}{'classifier said':<20}{'n':>4}")
    for (said, pred), n in sorted(confusion.items()):
        print(f"{said:<18}{pred:<20}{n:>4}")
    if n_none:
        print(f"\nfalse positives on 'none' windows: {fp_none}/{n_none}")
    per = defaultdict(lambda: [0, 0, 0])
    for (said, pred), n in confusion.items():
        per[said][0] += n
        per[said][1] += n if pred == said else 0
    for (said, pred), n in confusion.items():
        if pred != "(unlabelled)":
            per[pred][2] += n
    print("\nshape            labelled  hit  predicted-total")
    for s, (tot, hit, predn) in sorted(per.items()):
        print(f"{s:<17}{tot:>8}{hit:>5}{predn:>10}")


if __name__ == "__main__":
    main()
