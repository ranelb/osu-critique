#!/usr/bin/env python3
"""Judge drift: how far does our judgement sit from the game's own counts?

This is the measurement the edge guard was chosen with, and the tool to re-run
after any change to the judgement. For every replay it can pair with a map, it
compares the judged count vector against the replay's recorded one and reports
the weighted drift (``count_distance``: 2*miss + 100 + 50 + 0.5*300) plus, on
request, what alternative window guards would do.

    python scripts/judge_drift.py                 # summary: exact %, mean L1, slices
    python scripts/judge_drift.py --per-run       # also one line per replay
    python scripts/judge_drift.py --guard-sweep   # what 0.0/0.5/1.0/1.5 ms would do

It mirrors ``report.analyze`` (score-block rate, HR/EZ-adjusted OD/CS, the
[player_scale, 1.0] calibration), so its numbers are the pipeline's. A replay
it cannot judge is counted under its reason and never aborts the run: slider
0.8.4 refuses lazer exports whose life-bar offsets are floats, and those
frames cannot be read, so they are reported as skipped, not silently dropped.

Read it before touching ``classify()`` or the calibration: the counts are the
only ground truth we have per play, and the drift is where a change shows up as
a number. Note that the population is a local replay corpus, so this script is
a development tool, not something CI can run.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from osu_critique.io import pairing  # noqa: E402
from osu_critique.io.beatmap import (build_objects, circle_radius, cs_for,  # noqa: E402
                                     load_beatmap, mod_scale, od_for, od_windows)
from osu_critique.io.replay import (build_frames, find_presses, load_replay,  # noqa: E402
                                    read_score_meta)
from osu_critique.metrics.assignment import EDGE_GUARD_MS, classify, judge  # noqa: E402
from osu_critique.report import build_trust, count_distance  # noqa: E402

GUARDS = (0.0, 0.5, 1.0, 1.5)


def counts_with_guard(results, w, guard):
    det = {"300": 0, "100": 0, "50": 0, "miss": 0}
    for x in results:
        if x.get("error") is None:
            det[x["result"]] += 1
        else:
            det[classify(x["error"], w[0], w[1], w[2], guard)] += 1
    return det


def measure(rp, mp):
    """Judge one replay the way ``report.analyze`` does.

    Returns a record dict, or ``(reason, detail)`` when the replay is skipped.
    """
    try:
        r = load_replay(rp)
        bm = load_beatmap(mp)
        r.beatmap = bm
    except Exception as e:                      # noqa: BLE001 -- one bad file is a skip
        return ("unparseable", f"{type(e).__name__}: {e}"[:80])
    if r.relax or r.auto_pilot:
        return ("relax/autopilot", "")
    meta = read_score_meta(rp)
    frames = build_frames(r)
    times = np.array([f[0] for f in frames])
    presses = find_presses(frames)
    press_times = [x[0] for x in presses]
    player_scale = mod_scale(r, meta)
    od = od_for(bm, r)
    radius = circle_radius(cs_for(bm, r))
    rec = {"300": r.count_300, "100": r.count_100, "50": r.count_50,
           "miss": r.count_miss}
    best = None
    for scale in dict.fromkeys([player_scale, 1.0]):
        objs = build_objects(bm, scale, hard_rock=r.hard_rock)
        w = od_windows(od, scale)
        res, det, _ = judge(objs, frames, times, presses, press_times,
                            w[0], w[1], w[2], radius,
                            max(250.0, ((200 - 10 * od) + 120) * scale),
                            spinner_od=od, scale=scale)
        d = count_distance(det, rec)
        if best is None or d < best["l1"]:
            best = {"l1": d, "scale": scale, "w": w, "res": res, "det": det,
                    "objs": objs}
    judged = sum(rec.values())
    trust = build_trust(best["det"], rec, best["scale"], player_scale, judged,
                        False, False, relax=False)
    n_spin = sum(1 for o in best["objs"] if o["kind"] == "Spinner")
    return {"rec": rec, "det": best["det"], "l1": best["l1"], "w": best["w"],
            "res": best["res"], "scale": best["scale"], "n_spin": n_spin,
            "n_obj": len(best["objs"]), "overridden": best["scale"] != player_scale,
            "trusted": trust["trustworthy"], "within": trust["within_tolerance"],
            "title": bm.title}


def _slice(name, rows):
    if not rows:
        return f"  {name:28s} n=0"
    ex = sum(1 for x in rows if x["l1"] == 0)
    return (f"  {name:28s} n={len(rows):5d}  exact {ex:5d} = {100 * ex / len(rows):5.1f}%"
            f"  mean L1 {sum(x['l1'] for x in rows) / len(rows):6.2f}"
            f"  total L1 {sum(x['l1'] for x in rows):8.0f}")


def run(guard_sweep=False, per_run=False):
    rows = []
    skipped = Counter()
    examples = {}
    totals = {g: 0.0 for g in GUARDS}
    exact = {g: 0 for g in GUARDS}
    sweep_rows = {g: [] for g in GUARDS}
    for _src, rp, mp in pairing.pair_all():
        out = measure(rp, mp)
        if isinstance(out, tuple):
            skipped[out[0]] += 1
            examples.setdefault(out[0], out[1])
            continue
        rows.append(out)
        if per_run:
            print(f"{out['title'][:34]:34s} {'ok' if out['trusted'] else 'UNTRUSTED':9s} spin={out['n_spin']:2d} {str(out['rec']):>22} "
                  f"{str(out['det']):>22} L1 {out['l1']:6.1f} "
                  f"{'ok' if out['within'] else 'DRIFT'}")
        if guard_sweep:
            for g in GUARDS:
                d2 = count_distance(counts_with_guard(out["res"], out["w"], g), out["rec"])
                totals[g] += d2
                exact[g] += d2 == 0
                sweep_rows[g].append({"l1": d2, "n_spin": out["n_spin"]})
        del out["res"]
    n = len(rows)
    print(f"\n{n} non-relax plays judged; skipped: "
          f"{dict(skipped) if skipped else 'none'}")
    for reason, ex in examples.items():
        if ex:
            print(f"  skip reason '{reason}', e.g. {ex}")
    if not n:
        return
    print("\ndrift vs the game's recorded counts:")
    print(_slice("all", rows))
    print(_slice("has spinner", [x for x in rows if x["n_spin"]]))
    print(_slice("no spinner", [x for x in rows if not x["n_spin"]]))
    print(f"  untrustworthy by build_trust: {sum(1 for x in rows if not x['trusted'])}/{n};"
          f" calibration overrode the rate flag: {sum(1 for x in rows if x['overridden'])}/{n}")
    if guard_sweep:
        print("\nguard sweep (would-be totals; exact / mean L1, spinner runs split):")
        for g in GUARDS:
            note = "  <-- current" if abs(g - EDGE_GUARD_MS) < 1e-9 else ""
            sp = [x for x in sweep_rows[g] if x["n_spin"]]
            ns = [x for x in sweep_rows[g] if not x["n_spin"]]
            def f(v):
                return (f"{sum(1 for x in v if x['l1'] == 0):5d}/{len(v):5d} "
                        f"L1 {sum(x['l1'] for x in v) / max(1, len(v)):5.2f}")
            print(f"  {g:.1f} ms: total L1 {totals[g]:8.0f}  exact {int(exact[g]):5d}/{n}"
                  f" | no-spinner {f(ns)} | spinner {f(sp)}{note}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="how far the judgement sits from the game")
    ap.add_argument("--guard-sweep", action="store_true",
                    help="also show what 0.0/0.5/1.0/1.5 ms window guards would do")
    ap.add_argument("--per-run", action="store_true", help="print one line per replay")
    args = ap.parse_args(argv)
    run(args.guard_sweep, args.per_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
