"""Cursor autopsy: what the hand actually did, object by object.

This is the re-derivation that has answered every real question about a play so
far, and it is deliberately *not* part of the pipeline yet (see docs/ROADMAP.md,
item 1 + 2): the metrics JSON gives aggregates, this gives the hand.

    python scripts/autopsy.py <replay.osr> [--map MAP] [--out DIR] [--tag NAME] [--no-plots]

It works for normal replays and for Relax (RX) ones. Under RX the press-based
numbers are meaningless (the game taps for you), so the tap sections are skipped
and only the cursor sections are printed - which is exactly the aim measurement
you want from an RX play.

The numbers
-----------
aim (always)
    distance from the cursor to each object's centre **at the note instant** (the
    thing the game judges, and the thing a player can train), the closest
    approach within +/-320 ms and when it happens, the share of notes the cursor
    reached but not on time, and the ceiling curve: distance at the note against
    the cursor speed the jump demands.
taps (normal replays only)
    press-time aim error, hit-error bias, whiff causes, arrival margin
    distribution, per-leg path efficiency (is the cursor going where the pattern
    asks?) and mid-travel "stutter" presses.
shapes
    every 5-note window classified by its turn angles - near-reversal chains vs
    cornered/box windows vs flow - with the hit rate per class. Wide reversals
    and 90 degree boxes fail in completely different ways.
windows
    the worst stretches, drawn: object polyline, cursor path coloured by time,
    press markers, and the cursor position when each note was due.

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
                                     mod_scale, od_windows)
from osu_critique.io.replay import build_frames, cursor_at, find_presses, load_replay  # noqa: E402
from osu_critique.metrics.assignment import judge  # noqa: E402
from osu_critique.report import analyze  # noqa: E402

SAMPLE_MS = 3.0            # cursor sampling step
WINDOW_MS = 320.0          # how far either side of a note the cursor is followed
COL = {"300": "#39b54a", "100": "#e8c000", "50": "#e8892b", "miss": "#e02020"}


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
    rows = []
    for i, o in enumerate(objs):
        if o["kind"] == "Spinner":
            continue
        ts = np.arange(o["t"] - WINDOW_MS, o["t"] + WINDOW_MS + 1, SAMPLE_MS)
        pts = [cursor(t) for t in ts]
        ds = np.array([math.hypot(p[0] - o["x"], p[1] - o["y"]) for p in pts])
        k = int(ds.argmin())
        prev = objs[i - 1] if i else None
        gap = math.hypot(o["x"] - prev["x"], o["y"] - prev["y"]) if prev else None
        dt = (o["t"] - prev["t"]) if prev else None
        cxt, cyt = cursor(o["t"])
        ex, ey = cxt - o["x"], cyt - o["y"]
        u = ((o["x"] - prev["x"]) / gap, (o["y"] - prev["y"]) / gap) if gap else (0.0, 0.0)
        inside = np.where(ds <= radius)[0]
        rows.append(dict(i=i, t=o["t"], kind=o["kind"], x=o["x"], y=o["y"],
                         d=math.hypot(ex, ey) / radius, dmin=float(ds[k]) / radius,
                         peak_off=float(ts[k] - o["t"]),
                         entry_off=float(ts[inside[0]] - o["t"]) if len(inside) else None,
                         along=(ex * u[0] + ey * u[1]) / radius,
                         lat=abs(ex * -u[1] + ey * u[0]) / radius,
                         speed=(gap / dt) if gap and dt and dt > 0 else None,
                         gap_r=(gap / radius) if gap else None))
    n = len(rows)
    d = np.array([x["d"] for x in rows])
    dmin = np.array([x["dmin"] for x in rows])
    peak = np.array([x["peak_off"] for x in rows])
    along = np.array([x["along"] for x in rows])
    sp = np.array([x["speed"] if x["speed"] else np.nan for x in rows])
    gapr = np.array([x["gap_r"] if x["gap_r"] else np.nan for x in rows])
    ok = ~np.isnan(sp)

    print(f"\nAIM (n={n})")
    print(f"  at the note instant: mean {d.mean():.2f}r median {np.median(d):.2f}r p90 {np.percentile(d, 90):.2f}r "
          f"| inside the circle {100 * np.mean(d <= 1):.1f}%")
    print(f"  closest approach +/-{WINDOW_MS:.0f}ms: mean {dmin.mean():.2f}r median {np.median(dmin):.2f}r "
          f"| inside {100 * np.mean(dmin <= 1):.1f}% | never inside {int((dmin > 1).sum())}")
    print(f"  when the peak happens: median {np.median(peak):+.0f}ms | "
          f"{100 * np.mean(peak > 20):.0f}% late (>20ms), {100 * np.mean(peak < -20):.0f}% early")
    band = (dmin <= 1.0) & (d > 1.0)
    print(f"  reached but not on time (dmin<=1r, d>1r): {int(band.sum())} ({100 * band.mean():.1f}%)")
    print(f"  error shape: {100 * np.mean(along < 0):.0f}% stopped short, {100 * np.mean(along > 0):.0f}% overshot")
    print(f"  ceiling curve (required cursor speed -> distance at the note):")
    for lo, hi in ((0, .5), (.5, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 99)):
        s = ok & (sp >= lo) & (sp < hi)
        if s.sum() >= 5:
            print(f"     {lo:.1f}-{hi:<4.1f} px/ms  n={int(s.sum()):3d}  {d[s].mean():5.2f}r "
                  f"(p90 {np.percentile(d[s], 90):5.2f}r)  inside {100 * np.mean(d[s] <= 1):5.1f}%  "
                  f"peak {np.median(peak[s]):+4.0f}ms")
    print(f"  by jump distance:")
    for lo, hi in ((0, 3), (3, 5), (5, 7), (7, 9), (9, 99)):
        s = ~np.isnan(gapr) & (gapr >= lo) & (gapr < hi)
        if s.sum() >= 5:
            print(f"     {lo:.0f}-{hi:<3.0f}r  n={int(s.sum()):3d}  {d[s].mean():5.2f}r  inside {100 * np.mean(d[s] <= 1):5.1f}%")
    t0, t1 = rows[0]["t"], rows[-1]["t"]
    print(f"  over time ({(t1 - t0) / 1000:.0f}s play):")
    for k in range(6):
        a, b = t0 + k * (t1 - t0) / 6, t0 + (k + 1) * (t1 - t0) / 6
        s = np.array([a <= x["t"] < b for x in rows])
        if s.sum() >= 5:
            print(f"     {a / 1000:5.0f}-{b / 1000:5.0f}s n={int(s.sum()):3d}  {d[s].mean():5.2f}r "
                  f"(p90 {np.percentile(d[s], 90):5.2f}r)  inside {100 * np.mean(d[s] <= 1):5.1f}%  "
                  f"peak {np.median(peak[s]):+4.0f}ms")

    # ----------------------------------------------------------------- taps --
    if not rx:
        errs = np.array([x["error"] for x in results if x["error"] is not None])
        aims = np.array([x["aim"] / radius for x in results if x["aim"] is not None])
        print(f"\nTAPS")
        print(f"  bias {errs.mean():+.1f}ms ({100 * np.mean(errs < 0):.0f}% early) std {errs.std():.1f}ms "
              f"UR {errs.std() * 10:.1f} = {100 * errs.std() / w300:.0f}% of the 300-window")
        print(f"  press-time aim: mean {aims.mean():.2f}r p90 {np.percentile(aims, 90):.2f}r "
              f">0.8r {100 * np.mean(aims > 0.8):.1f}% | max {aims.max():.2f}r")
        w = whiff_info
        print(f"  whiffs {w['n']}: mash {w['mash']} off_target {w['off_target']} slider_head {w['slider_head']} "
              f"lost {w['lost']} after_end {w['after_end']}")
        # per-leg heading match + stutter
        offs, effs, stutter, legs = [], [], 0, 0
        consumed = {x["press_t"] for x in results if x["press_t"] is not None}
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
            legs += 1
        for p, _k in find_presses(frames):
            j = min(range(len(objs)), key=lambda k: abs(objs[k]["t"] - p))
            if p < objs[j]["t"] and (objs[j]["t"] - p) > 40:
                c = cursor(p)
                if math.hypot(c[0] - objs[j]["x"], c[1] - objs[j]["y"]) / radius > 2.5:
                    stutter += 1
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
    print(f"\nSHAPES (5-note windows)")
    for cls, idxs in sorted(classes.items(), key=lambda kv: -len(kv[1])):
        if len(idxs) < 8:
            continue
        aim_here = np.array([rows[j]["d"] for j in idxs if j < len(rows)])
        res_here = [results[j]["result"] for j in idxs if j < len(results)]
        nb = sum(1 for r_ in res_here if r_ != "300")
        print(f"  {cls:22s} n={len(idxs):3d}  distance at note {aim_here.mean():.2f}r  "
              f"non-300 {nb} ({100 * nb / len(res_here):.1f}%)")

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
    a.hist(peak, bins=np.arange(-160, 161, 10), color="#7a9c7a")
    a.axvline(0, color="#333333", lw=2)
    for x in (-20, 20):
        a.axvline(x, color="#e02020", lw=1.4, ls="--")
    a.set_xlabel("when the cursor is closest to the object (ms vs the note)")
    a.set_ylabel("objects")
    a.set_title(f"(b) arrival timing: median {np.median(peak):+.0f} ms\n"
                f"{100 * np.mean(peak > 20):.0f}% peak late, {100 * np.mean(peak < -20):.0f}% early")

    a = ax[0][2]
    sc = a.scatter(np.array([x["along"] for x in rows]) * radius,
                   np.array([x["lat"] for x in rows]) * radius,
                   c=sp, cmap="plasma", s=10, alpha=0.7)
    a.add_patch(plt.Circle((0, 0), radius, fill=False, color="#e02020", lw=2))
    a.axvline(0, color="#888888", lw=0.8); a.axhline(0, color="#888888", lw=0.8)
    a.set_xlabel("error along the travel axis (px): negative = short")
    a.set_ylabel("lateral error (px)")
    a.set_title(f"(c) target frame: {100 * np.mean(along < 0):.0f}% short, {100 * np.mean(along > 0):.0f}% past")
    a.set_aspect("equal"); a.set_xlim(-160, 160); a.set_ylim(-160, 160)
    plt.colorbar(sc, ax=a, label="required speed (px/ms)")

    a = ax[1][0]
    xs, m_, p9, ins = [], [], [], []
    for k in range(int((t1 - t0) / 10000)):
        lo, hi = t0 + k * 10000, t0 + (k + 1) * 10000
        s = np.array([lo <= x["t"] < hi for x in rows])
        if s.sum() >= 5:
            xs.append((lo + hi) / 2000)
            m_.append(d[s].mean())
            p9.append(np.percentile(d[s], 90))
            ins.append(100 * np.mean(d[s] <= 1))
    a.plot(xs, m_, "-o", color="#10305a", label="mean distance at the note")
    a.plot(xs, p9, "--", color="#c0392b", label="p90")
    a.axhline(1.0, color="#e02020", lw=1.6)
    a2 = a.twinx()
    a2.plot(xs, ins, ":", color="#2e8b57", lw=2, label="% inside")
    a2.set_ylabel("% of notes with the cursor inside", color="#2e8b57"); a2.set_ylim(0, 100)
    a.set_xlabel("map time (s)"); a.set_ylabel("distance at the note (radii)")
    a.set_title("(d) drift through the play"); a.legend(fontsize=9, loc="upper left")

    a = ax[1][1]
    sc = a.scatter([x["x"] for x in rows], [x["y"] for x in rows],
                   c=np.clip(d, 0, 2.5), cmap="RdYlGn_r", s=14, alpha=0.85)
    a.set_xlim(0, 512); a.set_ylim(384, 0); a.set_aspect("equal")
    a.set_title("(e) where on the playfield"); plt.colorbar(sc, ax=a, label="distance (radii)")

    a = ax[1][2]
    mm = dmin <= 1.0
    a.scatter(dmin[mm], d[mm], s=9, alpha=0.5, color="#3b6ea5", label="inside at some point")
    a.scatter(dmin[~mm], d[~mm], s=14, alpha=0.9, color="#e02020", label="never inside")
    a.scatter(dmin[band], d[band], s=12, alpha=0.55, color="#f0a020",
              label=f"inside, not at the note ({int(band.sum())})")
    a.plot([0, 3], [0, 3], color="#999999", lw=1, ls=":")
    a.axhline(1.0, color="#e02020", lw=1.4); a.axvline(1.0, color="#e02020", lw=1.4)
    a.set_xlabel(f"best approach within +/-{WINDOW_MS:.0f} ms (radii)")
    a.set_ylabel("distance at the note instant (radii)")
    a.set_title(f"(f) {100 * band.mean():.0f}% of notes: there, just not then")
    a.legend(fontsize=8); a.set_xlim(0, 3); a.set_ylim(0, 4.5)

    plt.suptitle(f"{metrics['map']} [{metrics['mod_string']}] - cursor autopsy "
                 f"({n} objects, AR {bm.ar():.1f}/OD {bm.od():.1f}, {radius:.0f}px circles)", fontsize=13)
    plt.tight_layout(rect=(0, 0, 1, 0.965))
    aim_png = os.path.join(args.out, f"{tag}_aim.png")
    plt.savefig(aim_png, dpi=105)
    plt.close()

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
    if picks:
        fig, axes = plt.subplots(1, len(picks), figsize=(7.6 * len(picks), 7.4), squeeze=False)
        for axx, (score, i) in zip(axes[0], picks):
            lo, hi = max(0, i - 2), min(len(objs) - 1, i + 4)
            t_a, t_b = objs[lo]["t"] - 80, objs[hi]["t"] + 160
            ts = np.arange(t_a, t_b, 4)
            pts = np.array([cursor(t) for t in ts])
            axx.plot(pts[:, 0], pts[:, 1], "-", color="#c8c8c8", lw=1, zorder=1)
            axx.scatter(pts[:, 0], pts[:, 1], c=ts, cmap="viridis", s=7, zorder=2)
            axx.plot([o["x"] for o in objs[lo:hi + 1]], [o["y"] for o in objs[lo:hi + 1]],
                     "--", color="#8888ff", lw=1.2, zorder=3)
            for k in range(lo, hi + 1):
                o = objs[k]
                dd = math.hypot(cursor(o["t"])[0] - o["x"], cursor(o["t"])[1] - o["y"]) / radius
                col = "#e02020" if dd > 1 else ("#e8c000" if dd > 0.7 else "#39b54a")
                axx.add_patch(plt.Circle((o["x"], o["y"]), radius, color=col, alpha=0.45, zorder=4))
                axx.text(o["x"] + radius * 0.85, o["y"] - radius * 0.85, str(k), fontsize=9, zorder=6)
                c = cursor(o["t"])
                axx.plot([c[0]], [c[1]], "*", ms=13, color=col, zorder=8)
                if dd > 1:
                    axx.plot([c[0], o["x"]], [c[1], o["y"]], "-", color="#e02020", lw=1.5, zorder=7)
            axx.set_xlim(-14, 526); axx.set_ylim(398, -14); axx.set_aspect("equal")
            axx.set_xticks([]); axx.set_yticks([])
            axx.set_title(f"t={rows[i]['t'] / 1000:.1f}s  mean {score:.2f}r at the note\n"
                          f"ring colour = distance when the note was due, star = cursor then", fontsize=10.5)
        plt.suptitle(f"{metrics['map']} - cursor path (viridis = time) against the pattern, worst stretches",
                     fontsize=12)
        plt.tight_layout(rect=(0, 0, 1, 0.93))
        win_png = os.path.join(args.out, f"{tag}_windows.png")
        plt.savefig(win_png, dpi=110)
        plt.close()
        print(f"\nfigures: {aim_png}\n         {win_png}")
    else:
        print(f"\nfigure: {aim_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
