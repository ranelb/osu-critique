#!/usr/bin/env python3
"""Judge drift: how far does our judgement sit from the game's own counts?

This is the measurement the edge guard was chosen with, and the tool to re-run
after any change to the judgement. For every replay it can pair with a map, it
compares the judged count vector against the replay's recorded one and reports
the weighted drift (``count_distance``: 2*miss + 100 + 50 + 0.5*300) plus, on
request, what alternative window guards would do.

    python scripts/judge_drift.py                 # current judgement, per map + total
    python scripts/judge_drift.py --guard-sweep   # what 0.0/0.5/1.0/1.5 ms would do

Read it before touching ``classify()`` or the calibration: the counts are the
only ground truth we have per play, and the drift is where a change shows up as
a number. Note that the population is the *author's* replays, so this script is
a development tool, not something CI can run.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from osu_critique.io import pairing  # noqa: E402
from osu_critique.io.beatmap import (build_objects, circle_radius, load_beatmap,  # noqa: E402
                                     mod_scale, od_windows)
from osu_critique.io.replay import build_frames, find_presses, load_replay  # noqa: E402
from osu_critique.metrics.assignment import EDGE_GUARD_MS, classify, judge  # noqa: E402
from osu_critique.report import count_distance, build_trust  # noqa: E402

GUARDS = (0.0, 0.5, 1.0, 1.5)


def counts_with_guard(results, w, guard):
    det = {"300": 0, "100": 0, "50": 0, "miss": 0}
    for x in results:
        if x.get("error") is None:
            det[x["result"]] += 1
        else:
            det[classify(x["error"], w[0], w[1], w[2], guard)] += 1
    return det


def run(guard_sweep=False):
    warnings_needed = 0
    totals = {g: 0.0 for g in GUARDS}
    exact = {g: 0 for g in GUARDS}
    n_maps = 0
    print(f"{'map':34s} {'od':>4} {'w300':>6} {'recorded':>22} {'detected':>22} {'L1':>6}  trust")
    for _src, rp, mp in pairing.pair_all():
        try:
            r = load_replay(rp)
            bm = load_beatmap(mp)
            r.beatmap = bm
        except Exception:
            continue
        if r.relax or r.auto_pilot:
            continue
        frames = build_frames(r)
        times = np.array([f[0] for f in frames])
        radius = circle_radius(bm.cs())
        rec = {"300": r.count_300, "100": r.count_100, "50": r.count_50,
               "miss": r.count_miss}
        # the pipeline's own calibration: the scale with the lowest drift wins
        best = None
        for scale in dict.fromkeys([mod_scale(r), 1.0]):
            objs = build_objects(bm, scale, hard_rock=r.hard_rock)
            w = od_windows(bm.od(), scale)
            p = find_presses(frames)
            pt = [x[0] for x in p]
            res, det, _ = judge(objs, frames, times, p, pt, w[0], w[1], w[2],
                                radius, max(250.0, ((200 - 10 * bm.od()) + 120) * scale))
            d = count_distance(det, rec)
            if best is None or d < best[0]:
                best = (d, scale, w, res, det)
        _d, scale, w, res, det = best
        if scale != mod_scale(r):
            continue                      # frames are not in this map's time base
        n_maps += 1
        l1 = count_distance(det, rec)
        trust = build_trust(det, rec, scale, mod_scale(r), sum(rec.values()),
                            False, False, relax=False)
        if not trust["within_tolerance"]:
            warnings_needed += 1
        title = os.path.basename(bm.title)[:32]
        print(f"{title:34s} {bm.od():4.1f} {w[0]:6.1f} {str(rec):>22} {str(det):>22} "
              f"{l1:6.1f}  {'ok' if trust['within_tolerance'] else 'DRIFT'}")
        if guard_sweep:
            for g in GUARDS:
                d2 = counts_with_guard(res, w, g)
                totals[g] += count_distance(d2, rec)
                if count_distance(d2, rec) == 0:
                    exact[g] += 1
    print(f"\n{n_maps} plays compared; {warnings_needed} outside tolerance")
    if guard_sweep:
        print("\nguard sweep (would-be totals):")
        for g in GUARDS:
            note = "  <-- current" if abs(g - EDGE_GUARD_MS) < 1e-9 else ""
            print(f"  {g:.1f} ms guard: total L1 {totals[g]:7.0f}   exact {exact[g]:3d}/{n_maps}{note}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="how far the judgement sits from the game")
    ap.add_argument("--guard-sweep", action="store_true",
                    help="also show what 0.0/0.5/1.0/1.5 ms window guards would do")
    args = ap.parse_args(argv)
    run(args.guard_sweep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
