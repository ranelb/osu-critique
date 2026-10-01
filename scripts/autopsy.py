"""Cursor autopsy: what the hand actually did, object by object.

This is the re-derivation that answered every real question about a play so far.
It works for normal replays and for Relax (RX) ones. The **aim** numbers are now
the library's ``metrics.aim`` block (they also live in ``metrics["aim_mode"]`` of
every ``analyze`` run, with the six-panel figure); this script keeps the extra
views that are still exploratory: taps, shape classes and the worst stretches,
drawn.

    python scripts/autopsy.py <replay.osr> [--map MAP] [--out DIR] [--tag NAME] [--no-plots]

The numbers
-----------
aim (always)
    the cursor-arrival block: distance at the note instant, closest approach
    within +/-320 ms and when it happens, the share reached but not on time, the
    along/lateral split and the ceiling curve (distance at the note against the
    cursor speed the jump demands). Identical to ``metrics.aim_mode``.
taps (normal replays only)
    press-time aim error, hit-error bias, whiff causes, per-leg path efficiency
    (is the cursor going where the pattern asks?) and mid-travel "stutter"
    presses.
shapes
    every 5-note window classified by its turn angles - near-reversal chains vs
    cornered/box windows vs flow - with the hit rate per class.
windows
    the worst stretches, drawn: object polyline and the cursor position when each
    note was due.

Dependencies: numpy (+ matplotlib for the figures). Everything else comes from
the package itself.
"""
from __future__ import annotations

import argparse
import collections
import math
import os
import statistics as st
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np  # noqa: E402

from osu_critique.io import pairing  # noqa: E402
from osu_critique.io.beatmap import (build_objects, circle_radius, load_beatmap,  # noqa: E402
                                     od_windows)
from osu_critique.io.replay import build_frames, cursor_at, find_presses, load_replay  # noqa: E402
from osu_critique.metrics.aim import build_aim, describe  # noqa: E402
from osu_critique.metrics.assignment import judge  # noqa: E402
from osu_critique.report import analyze  # noqa: E402


def resolve_map(replay_path, explicit=None):
    if explicit:
        return explicit
    base = os.path.basename(replay_path)
    for _src, rp, mp in pairing.pair_all():
        if os.path.basename(rp) == base:
            return mp
    raise SystemExit(f"no map paired with {base!r} - pass --map")


def turn_angle(a, b, c):
    v1 = (b["x"] - a["x"], b["y"] - a["y"])
    v2 = (c["x"] - b["x"], c["y"] - b["y"])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1 or n2 < 1:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))))


def shape_class(objs, i):
    """Classify the 5-note window around object ``i`` by its turns."""
    if i < 2 or i > len(objs) - 3:
        return None
    turns = [t for t in (turn_angle(objs[k - 2], objs[k - 1], objs[k]) for k in range(i - 1, i + 3))
             if t is not None]
    if len(turns) < 2:
        return None
    sharp = sum(1 for t in turns if t > 120)
    corners = sum(1 for t in turns if 55 <= t <= 120)
    if sharp >= len(turns) - 1 and sharp >= 2:
        return "near-reversal chain"
    if corners >= 2:
        return "cornered (box)"
    if all(t < 55 for t in turns):
        return "flow (arc/line)"
    return "mixed"


def main(argv=None):
    ap = argparse.ArgumentParser(description="cursor autopsy for one replay")
    ap.add_argument("replay")
    ap.add_argument("--map", default=None, help="beatmap .osu (default: auto-pair by md5)")
    ap.add_argument("--out", default="out/autopsy", help="where the figures go")
    ap.add_argument("--tag", default=None, help="name for the output files")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args(argv)

    tag = args.tag or os.path.splitext(os.path.basename(args.replay))[0][:40].strip().replace(" ", "_")
    map_path = resolve_map(args.replay, args.map)

    # the pipeline run gives the calibrated scale and the trust block
    metrics = analyze(args.replay, map_path, tag=tag, outdir=args.out, console=False,
                      write_objects=False)
    scale = metrics["time_scale"]
    r = load_replay(args.replay)
    bm = load_beatmap(map_path)
    r.beatmap = bm
    frames = build_frames(r)
    times = np.array([f[0] for f in frames])
    radius = circle_radius(bm.cs())
    w300, w100, w50 = od_windows(bm.od(), scale)
    objs = build_objects(bm, scale, hard_rock=metrics["mods"].get("HR", False))
    cursor = lambda t: cursor_at(frames, times, t)  # noqa: E731
    rx = bool(metrics["mods"].get("RX") or metrics["mods"].get("AP"))

    press_times = [p[0] for p in find_presses(frames)]
    results, detected, whiff_info = judge(objs, frames, times, find_presses(frames), press_times,
                                          w300, w100, w50, radius,
                                          max(250.0, ((200 - 10 * bm.od()) + 120) * scale))
    trust = metrics["trust"]
    print(f"MAP  {metrics['map']}  [{metrics['mod_string']}]  md5 {metrics['beatmap_md5'][:10]}")
    print(f"     {len(objs)} objects | CS {bm.cs():.1f} AR {bm.ar():.1f} OD {bm.od():.1f} | "
          f"radius {radius:.1f}px | windows {w300:.0f}/{w100:.0f}/{w50:.0f} ms | time scale {scale} "
          f"({metrics['windows_ms']['300']:.0f} ms calibrated)")
    print(f"     recorded {metrics['counts_recorded']} | detected {detected} | "
          f"trustworthy {trust['trustworthy']} | {trust['notes'] or 'within tolerance'}")
    if rx:
        print("     RELAX: taps are the game's, so only the cursor sections below mean anything")

    # ------------------------------------------------------------------ aim --
    block, rows = build_aim(objs, frames, times, radius, is_relax=rx)
    for line in describe(block):
        print(("\n" + line) if line.startswith("AIM") else line)

    # ----------------------------------------------------------------- taps --
    if not rx and results:
        errs = np.array([x["error"] for x in results if x["error"] is not None])
        aims = np.array([x["aim"] / radius for x in results if x["aim"] is not None])
        print(f"\nTAPS")
        if errs.size:
            print(f"  bias {errs.mean():+.1f}ms ({100 * np.mean(errs < 0):.0f}% early) std {errs.std():.1f}ms "
                  f"UR {errs.std() * 10:.1f} = {100 * errs.std() / w300:.0f}% of the 300-window")
        if aims.size:
            print(f"  press-time aim: mean {aims.mean():.2f}r p90 {np.percentile(aims, 90):.2f}r "
                  f">0.8r {100 * np.mean(aims > 0.8):.1f}% | max {aims.max():.2f}r")
        w = whiff_info
        print(f"  whiffs {w['n']}: mash {w['mash']} off_target {w['off_target']} slider_head {w['slider_head']} "
              f"lost {w['lost']} after_end {w['after_end']}")
        # per-leg heading match + stutter
        offs, effs, stutter = [], [], 0
        for i in range(1, len(objs)):
            p_prev, p_cur = objs[i - 1], objs[i]
            req = math.degrees(math.atan2(p_cur["y"] - p_prev["y"], p_cur["x"] - p_prev["x"]))
            c0, c1 = cursor(p_prev["t"]), cursor(p_cur["t"])
            act = math.degrees(math.atan2(c1[1] - c0[1], c1[0] - c0[0]))
            offs.append(abs((req - act + 180) % 360 - 180))
            pts = [cursor(t) for t in np.arange(p_prev["t"], p_cur["t"], 6)]
            walked = sum(math.hypot(pts[j][0] - pts[j - 1][0], pts[j][1] - pts[j - 1][1])
                         for j in range(1, len(pts)))
            direct = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
            if direct > 1:
                effs.append(direct / max(1e-6, walked))
        for p, _k in find_presses(frames):
            j = min(range(len(objs)), key=lambda k: abs(objs[k]["t"] - p))
            if p < objs[j]["t"] and (objs[j]["t"] - p) > 40:
                c = cursor(p)
                if math.hypot(c[0] - objs[j]["x"], c[1] - objs[j]["y"]) / radius > 2.5:
                    stutter += 1
        if offs:
            print(f"  cursor direction matches the pattern within {st.median(offs):.0f}deg median "
                  f"(p90 {np.percentile(offs, 90):.0f}deg); path efficiency median {st.median(effs):.2f}, "
                  f"<0.7 in {100 * np.mean([e < 0.7 for e in effs]):.1f}% of legs")
        print(f"  mid-travel presses (stutter): {stutter} of {len(press_times)} "
              f"({100 * stutter / max(1, len(press_times)):.1f}%)")

    # --------------------------------------------------------------- shapes --
    classes = collections.defaultdict(list)
    for i, o in enumerate(objs):
        cls = shape_class(objs, i)
        if cls:
            classes[cls].append(i)
    if classes:
        by_i = {x["i"]: x for x in rows}
        print(f"\nSHAPES (5-note windows)")
        for cls, idxs in sorted(classes.items(), key=lambda kv: -len(kv[1])):
            if len(idxs) < 8:
                continue
            here = [by_i[j] for j in idxs if j in by_i]
            res_here = [results[j]["result"] for j in idxs if j < len(results)]
            nb = sum(1 for r_ in res_here if r_ != "300")
            print(f"  {cls:22s} n={len(idxs):3d}  distance at note "
                  f"{np.mean([h['d'] for h in here]):.2f}r  "
                  f"non-300 {nb} ({100 * nb / max(1, len(res_here)):.1f}%)")

    # --------------------------------------------------------------- worst ---
    worst = sorted(rows, key=lambda x: -x["d"])[:8]
    print("\nWORST arrivals (distance at the note instant)")
    for x in worst:
        print(f"  #{x['i']:4d} t={x['t'] / 1000:6.1f}s {x['kind']:6s} {x['d']:5.2f}r | closest {x['dmin']:4.2f}r "
              f"at {x['peak_off']:+4.0f}ms | speed {(x['speed'] or 0):4.2f}px/ms gap {(x['gap_r'] or 0):4.1f}r")

    if args.no_plots:
        return 0
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(matplotlib not installed: skipping the figures)")
        return 0

    os.makedirs(args.out, exist_ok=True)
    from osu_critique.charts import render_aim_charts
    aim_png = render_aim_charts(
        rows, radius, block["window_ms"], tag, args.out,
        title=f"{metrics['map']} [{metrics['mod_string']}] "
              f"(AR {bm.ar():.1f}/OD {bm.od():.1f}, {radius:.0f}px circles)")

    # worst stretches: rank 4-note windows by their mean distance at the note
    scored = []
    for i in range(1, len(rows) - 3):
        win = rows[i:i + 4]
        if any(x["gap_r"] is None or x["gap_r"] < 4 for x in win):
            continue
        scored.append((st.mean([x["d"] for x in win]), i))
    scored.sort(reverse=True)
    picks, used = [], []
    for score, i in scored:
        if any(abs(i - j) < 12 for j in used):
            continue
        picks.append((score, i))
        used.append(i)
        if len(picks) == 3:
            break
    by_i = {x["i"]: x for x in rows}
    win_png = None
    if picks:
        fig, axes = plt.subplots(1, len(picks), figsize=(7.6 * len(picks), 7.4), squeeze=False)
        for axx, (score, i) in zip(axes[0], picks):
            win = rows[i:i + 4]
            lo, hi = max(0, win[0]["i"] - 2), win[-1]["i"] + 2
            seq = [by_i[k] for k in range(lo, hi + 1) if k in by_i]
            ts = np.arange(seq[0]["t"] - 80, seq[-1]["t"] + 160, 4)
            pts = np.array([cursor(t) for t in ts])
            axx.plot(pts[:, 0], pts[:, 1], "-", color="#c8c8c8", lw=1, zorder=1)
            axx.scatter(pts[:, 0], pts[:, 1], c=ts, cmap="viridis", s=7, zorder=2)
            axx.plot([o["x"] for o in seq], [o["y"] for o in seq],
                     "--", color="#8888ff", lw=1.2, zorder=3)
            for o in seq:
                col = "#e02020" if o["d"] > 1 else ("#e8c000" if o["d"] > 0.7 else "#39b54a")
                axx.add_patch(plt.Circle((o["x"], o["y"]), radius, color=col, alpha=0.45, zorder=4))
                axx.text(o["x"] + radius * 0.85, o["y"] - radius * 0.85, str(o["i"]), fontsize=9, zorder=6)
                c = cursor(o["t"])
                axx.plot([c[0]], [c[1]], "*", ms=13, color=col, zorder=8)
                if o["d"] > 1:
                    axx.plot([c[0], o["x"]], [c[1], o["y"]], "-", color="#e02020", lw=1.5, zorder=7)
            axx.set_xlim(-14, 526); axx.set_ylim(398, -14); axx.set_aspect("equal")
            axx.set_xticks([]); axx.set_yticks([])
            axx.set_title(f"t={win[0]['t'] / 1000:.1f}s  mean {score:.2f}r at the note\n"
                          f"ring colour = distance when the note was due, star = cursor then", fontsize=10.5)
        plt.suptitle(f"{metrics['map']} - cursor path (viridis = time) against the pattern, worst stretches",
                     fontsize=12)
        plt.tight_layout(rect=(0, 0, 1, 0.93))
        win_png = os.path.join(args.out, f"{tag}_windows.png")
        plt.savefig(win_png, dpi=110)
        plt.close()

    print(f"\nfigures: {aim_png}")
    if win_png:
        print(f"         {win_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
