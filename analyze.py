#!/usr/bin/env python3
"""
osu! replay critique pipeline
Parses a replay (.osr) + its map (.osu) and computes:
  - per-object hit error (timing) and aim error (spatial)
  - pattern classification (streams, jumps, sliders) and per-pattern stats
  - spatial (region) and temporal (over time) breakdowns
  - UR (unstable rate) style consistency metrics
Emits JSON metrics + PNG charts.
"""
import sys, os, json, bisect, math
import numpy as np
import slider

OUTDIR = "out"


def load(replay_path, map_path):
    r = slider.Replay.from_path(replay_path, retrieve_beatmap=False)
    bm = slider.Beatmap.from_path(map_path)
    r.beatmap = bm  # enables .hits/.accuracy (needs OD)
    return r, bm


def mod_scale(r):
    """map-time -> real-time multiplier (DT speeds up, HT slows down)."""
    if r.double_time:
        return 2.0 / 3.0
    if r.half_time:
        return 4.0 / 3.0
    return 1.0


def od_windows(od, scale):
    """judgement half-windows in real ms for 300/100/50."""
    w300 = (80 - 6 * od) * scale
    w100 = (140 - 8 * od) * scale
    w50 = (200 - 10 * od) * scale
    return w300, w100, w50


def build_frames(r):
    """list of (time_ms, x, y, keyA_down, keyB_down); keyA = K1|M1, keyB = K2|M2.
    Sorted by time (some export tools append out-of-order trailing frames)."""
    frames = []
    for a in r.actions:
        t = a.offset.total_seconds() * 1000.0
        frames.append((t, a.position.x, a.position.y,
                       bool(a.key1 or a.mouse1), bool(a.key2 or a.mouse2)))
    frames.sort(key=lambda f: f[0])
    return frames


def find_presses(frames):
    """detect rising edges on either tap button -> list of (time_ms, 'A'|'B')."""
    presses = []
    prev_a = prev_b = False
    for t, x, y, a_down, b_down in frames:
        if a_down and not prev_a:
            presses.append((t, "A"))
        if b_down and not prev_b:
            presses.append((t, "B"))
        prev_a, prev_b = a_down, b_down
    return presses


def build_objects(bm, scale):
    """list of dicts: {t, end, x, y, kind} with t/end in real ms."""
    objs = []
    for o in bm.hit_objects():
        kind = type(o).__name__
        t = o.time.total_seconds() * 1000.0 * scale
        end = getattr(o, "end_time", o.time)
        end = end.total_seconds() * 1000.0 * scale
        pos = o.position
        objs.append({"t": t, "end": end, "x": pos.x, "y": pos.y, "kind": kind})
    objs.sort(key=lambda d: d["t"])
    return objs


def cursor_at(frames, times, t):
    """linear-interpolated (x, y) at time t."""
    i = bisect.bisect_right(times, t)
    if i == 0:
        return frames[0][1], frames[0][2]
    if i >= len(frames):
        return frames[-1][1], frames[-1][2]
    t0, x0, y0, *_ = frames[i - 1]
    t1, x1, y1, *_ = frames[i]
    dt = t1 - t0
    if dt <= 0:
        return x1, y1
    f = (t - t0) / dt
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f


def classify(error, w300, w100, w50):
    ae = abs(error)
    if ae <= w300:
        return "300"
    if ae <= w100:
        return "100"
    if ae <= w50:
        return "50"
    return "miss"


def assign(objs, frames, times, presses, press_times, w300, w100, w50, radius, search, HIT_TOL):
    """greedy nearest-press assignment; returns (results, detected, whiffed)."""
    used = set()
    results = []
    for idx, o in enumerate(objs):
        lo = bisect.bisect_left(press_times, o["t"] - search)
        hi = bisect.bisect_right(press_times, o["t"] + search)
        best_i, best_d = None, None
        for j in range(lo, hi):
            if j in used:
                continue
            pt, key = presses[j]
            if o["kind"] == "Spinner":
                if not (o["t"] <= pt <= o["end"]):
                    continue
                d = abs(pt - o["t"])
            else:
                d = abs(pt - o["t"])
                # osu! only judges a press if the cursor is on the circle
                cx, cy = cursor_at(frames, times, pt)
                if math.hypot(cx - o["x"], cy - o["y"]) > radius * HIT_TOL:
                    continue
            if best_d is None or d < best_d:
                best_d, best_i = d, j
        if best_i is None:
            results.append({**o, "result": "miss", "error": None,
                            "aim": None, "key": None, "cursor_speed": None})
            continue
        used.add(best_i)
        pt, key = presses[best_i]
        error = pt - o["t"]
        res = classify(error, w300, w100, w50)
        cx, cy = cursor_at(frames, times, pt)
        aim = math.hypot(cx - o["x"], cy - o["y"]) if o["kind"] != "Spinner" else None
        sp = None
        i = bisect.bisect_right(times, pt)
        if 0 < i < len(frames) and times[i] > times[i - 1]:
            sp = math.hypot(frames[i][1] - frames[i - 1][1],
                            frames[i][2] - frames[i - 1][2]) / (times[i] - times[i - 1])
        results.append({**o, "result": res, "error": error, "aim": aim,
                        "key": key, "cursor_speed": sp})

    whiffed = len(presses) - len(used)
    detected = {"300": 0, "100": 0, "50": 0, "miss": 0}
    for x in results:
        detected[x["result"]] += 1
    return results, detected, whiffed


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_charts = "--charts" in sys.argv
    replay_path, map_path = args[0], args[1]
    tag = args[2] if len(args) > 2 else "run"

    r, bm = load(replay_path, map_path)

    frames = build_frames(r)
    times = np.array([f[0] for f in frames])
    presses = find_presses(frames)
    press_times = [p[0] for p in presses]
    radius = slider.beatmap.circle_radius(bm.cs())
    search_od = (200 - 10 * bm.od()) + 120  # 50-window + slack
    HIT_TOL = float(os.environ.get("HIT_TOL", "1.0"))

    recorded = {"300": r.count_300, "100": r.count_100,
                "50": r.count_50, "miss": r.count_miss}
    judged_total = sum(recorded.values())
    n_map_objects = len(bm.hit_objects())

    # try candidate time scales (mod-based first), keep the one whose detected
    # miss count agrees best with the recorded miss count
    candidates = [mod_scale(r), 1.0]
    best = None
    for scale in dict.fromkeys(candidates):  # dedupe, keep order
        objs = build_objects(bm, scale)
        w300, w100, w50 = od_windows(bm.od(), scale)
        search = max(250.0, search_od * scale)
        results, detected, whiffed = assign(objs, frames, times, presses,
                                            press_times, w300, w100, w50,
                                            radius, search, HIT_TOL)
        badness = abs(detected["miss"] - recorded["miss"])
        cand = {"scale": scale, "objs": objs, "results": results,
                "detected": detected, "whiffed": whiffed, "badness": badness,
                "w300": w300, "w100": w100, "w50": w50}
        if best is None or badness < best["badness"]:
            best = cand
    objs, results, detected, whiffed_presses = (best["objs"], best["results"],
                                                best["detected"], best["whiffed"])
    scale = best["scale"]
    w300, w100, w50 = best["w300"], best["w100"], best["w50"]
    if best["scale"] != mod_scale(r):
        print(f"!! calibrated time scale: mod-scale {mod_scale(r):.3f} -> {best['scale']:.3f} "
              f"(mod flag may be misleading)", file=sys.stderr)

    # version sanity: the map's last object must not be far beyond the replay end
    last_frame_t = float(times[-1]) if len(times) else 0.0
    last_obj_t = float(objs[-1]["t"]) if objs else 0.0
    map_version_mismatch = bool(objs) and last_obj_t > last_frame_t + 1000
    failed_play = bool(objs) and judged_total < n_map_objects - 2

    # --- metrics ---
    hits = [x for x in results if x["result"] != "miss"]
    errs = np.array([x["error"] for x in hits])
    aims = np.array([x["aim"] for x in hits if x["aim"] is not None])
    acc = float(r.accuracy) if hasattr(r, "accuracy") else None
    ur = float(np.std(errs) * 10) if len(errs) else None

    # spacing between consecutive objects (radius units) -> pattern buckets
    for i, x in enumerate(results):
        if i == 0:
            x["spacing_r"] = None
        else:
            p = results[i - 1]
            x["spacing_r"] = math.hypot(x["x"] - p["x"], x["y"] - p["y"]) / radius

    def bucket(sr):
        if sr is None:
            return "first"
        if sr <= 2.0:
            return "dense"
        if sr <= 4.0:
            return "stream"
        if sr <= 7.0:
            return "jump"
        return "bigjump"

    for x in results:
        x["pattern"] = bucket(x["spacing_r"])

    patterns = {}
    for x in results:
        p = x["pattern"]
        d = patterns.setdefault(p, {"n": 0, "miss": 0, "errs": []})
        d["n"] += 1
        if x["result"] == "miss":
            d["miss"] += 1
        elif x["error"] is not None:
            d["errs"].append(x["error"])

    # region breakdown (4 quadrants of 512x384)
    regions = {"TL": {"n": 0, "miss": 0, "aims": []}, "TR": {"n": 0, "miss": 0, "aims": []},
               "BL": {"n": 0, "miss": 0, "aims": []}, "BR": {"n": 0, "miss": 0, "aims": []}}
    for x in results:
        q = ("T" if x["y"] < 192 else "B") + ("L" if x["x"] < 256 else "R")
        d = regions[q]
        d["n"] += 1
        if x["result"] == "miss":
            d["miss"] += 1
        if x["aim"] is not None:
            d["aims"].append(x["aim"])

    # temporal quarters
    t0, t1 = results[0]["t"], results[-1]["t"]
    span = t1 - t0
    quarters = []
    for k in range(4):
        a, b = t0 + k * span / 4, t0 + (k + 1) * span / 4
        sel = [x for x in results if a <= x["t"] < b]
        qerr = [x["error"] for x in sel if x["error"] is not None]
        qmiss = sum(1 for x in sel if x["result"] == "miss")
        quarters.append({"range": [a, b], "n": len(sel), "miss": qmiss,
                         "mean_err": float(np.mean(qerr)) if qerr else None,
                         "std_err": float(np.std(qerr)) if qerr else None})

    # slider accuracy proxy: sliders with errors within 100 window
    sliders = [x for x in results if x["kind"] == "Slider"]
    slider_miss = sum(1 for x in sliders if x["result"] == "miss")

    # --- stream segments: runs of >=4 circles with stream/dense spacing ---
    streams, run = [], []
    for x in results:
        if x["kind"] == "Circle" and x["pattern"] in ("stream", "dense"):
            run.append(x)
        else:
            if len(run) >= 4:
                streams.append(run)
            run = []
    if len(run) >= 4:
        streams.append(run)

    stream_stats = []
    for s in streams:
        seg_errs = [x["error"] for x in s if x["error"] is not None]
        keys = [x["key"] for x in s if x["key"]]
        same_key = sum(1 for a, b in zip(keys, keys[1:]) if a == b)
        stream_stats.append({
            "t_start": round(s[0]["t"], 1), "t_end": round(s[-1]["t"], 1),
            "n": len(s),
            "miss": sum(1 for x in s if x["result"] == "miss"),
            "mean_err": float(np.mean(seg_errs)) if seg_errs else None,
            "std_err": float(np.std(seg_errs)) if seg_errs else None,
            "alt_ratio": 1 - same_key / max(1, len(keys) - 1),
            "key_pattern": "".join(keys)[:60],
        })

    # overall tapping consistency
    all_keys = [x["key"] for x in results if x["key"]]
    same_adj = sum(1 for a, b in zip(all_keys, all_keys[1:]) if a == b)
    tap = {"n": len(all_keys),
           "same_key_adjacent": same_adj,
           "same_key_pct": same_adj / max(1, len(all_keys) - 1),
           "alt_ratio": 1 - same_adj / max(1, len(all_keys) - 1)}

    # key usage
    key_usage = {"A": sum(1 for x in results if x["key"] == "A"),
                 "B": sum(1 for x in results if x["key"] == "B")}

    metrics = {
        "tag": tag,
        "player": r.player_name,
        "map": f"{bm.title} [{bm.version}]",        "mods": {"DT": r.double_time, "HT": r.half_time, "HD": r.hidden,
                 "HR": r.hard_rock, "NF": r.no_fail, "FL": r.flashlight, "EZ": r.easy},
        "difficulty": {"CS": bm.cs(), "AR": bm.ar(), "OD": bm.od(), "HP": bm.hp()},
        "counts_recorded": recorded,
        "counts_detected": detected,
        "map_version_mismatch": map_version_mismatch,
        "failed_play": failed_play,
        "n_objects_map": n_map_objects,
        "whiffed_presses": whiffed_presses,
        "accuracy": acc,
        "max_combo": r.max_combo,
        "full_combo": r.full_combo,
        "n_objects": len(results),
        "hit_error_ms": {"mean": float(np.mean(errs)) if len(errs) else None,
                         "std": float(np.std(errs)) if len(errs) else None,
                         "p10": float(np.percentile(errs, 10)) if len(errs) else None,
                         "p90": float(np.percentile(errs, 90)) if len(errs) else None,
                         "abs_mean": float(np.mean(np.abs(errs))) if len(errs) else None},
        "ur": ur,
        "early_pct": float(np.mean(errs < 0)) if len(errs) else None,
        "aim_px": {"mean": float(np.mean(aims)) if len(aims) else None,
                   "p90": float(np.percentile(aims, 90)) if len(aims) else None,
                   "mean_norm": float(np.mean(aims) / radius) if len(aims) else None},
        "key_usage": key_usage,
        "spacing_radius": radius,
        "patterns": {p: {"n": d["n"], "miss_rate": d["miss"] / d["n"],
                         "miss": d["miss"],
                         "mean_err": float(np.mean(d["errs"])) if d["errs"] else None,
                         "std_err": float(np.std(d["errs"])) if d["errs"] else None}
                     for p, d in patterns.items()},
        "regions": {q: {"n": d["n"], "miss_rate": d["miss"] / d["n"] if d["n"] else None,
                        "miss": d["miss"],
                        "mean_aim": float(np.mean(d["aims"])) if d["aims"] else None}
                    for q, d in regions.items()},
        "quarters": quarters,
        "sliders": {"n": len(sliders), "miss": slider_miss},
        "spinners": {"n": sum(1 for x in results if x["kind"] == "Spinner")},
        "streams": {"n_segments": len(stream_stats), "segments": stream_stats},
        "tapping": tap,
    }

    os.makedirs(OUTDIR, exist_ok=True)
    with open(f"{OUTDIR}/{tag}_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=float)

    # --- charts ---
    if do_charts and len(errs):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 2, figsize=(14, 9))
        # 1 hit error histogram
        ax = axes[0][0]
        ax.hist(errs, bins=40, color="#4a9", alpha=0.8)
        for w, c in [(w300, "#8f8"), (w100, "#ff8"), (w50, "#fa8")]:
            ax.axvline(w, color=c, ls="--", lw=1)
            ax.axvline(-w, color=c, ls="--", lw=1)
        ax.axvline(0, color="#fff", lw=1.5)
        ax.set_title(f"Hit error (ms)  mean={metrics['hit_error_ms']['mean']:.1f} std={metrics['hit_error_ms']['std']:.1f} UR={ur:.1f}")
        ax.set_xlabel("early < 0 | late > 0")

        # 2 timeline
        ax = axes[0][1]
        ts = [x["t"] for x in hits]
        ax.scatter(ts, [x["error"] for x in hits], s=6, alpha=0.4, c="#6cf")
        ax.scatter([x["t"] for x in results if x["result"] == "miss"],
                   [w50 + 5] * sum(1 for x in results if x["result"] == "miss"),
                   c="r", marker="x", label="misses")
        # rolling mean
        if len(ts) > 30:
            ts_a, err_a = np.array(ts), np.array([x["error"] for x in hits])
            k = max(5, len(ts_a) // 50)
            ker = np.ones(k) / k
            ax.plot(np.convolve(ts_a, ker, "same"), np.convolve(err_a, ker, "same"), c="#f80", lw=2)
        ax.axhline(0, color="#888", lw=1)
        ax.set_title("Hit error over time (orange = rolling mean, x = miss)")
        ax.set_ylabel("ms")

        # 3 spatial
        ax = axes[1][0]
        for x in results:
            c = {"300": "#3f3", "100": "#ff3", "50": "#fa3", "miss": "#f33"}[x["result"]]
            ax.scatter(x["x"], x["y"], s=6, c=c, alpha=0.7)
        ax.set_xlim(0, 512); ax.set_ylim(384, 0)
        ax.set_title("All objects colored by result (g/y/o/red = 300/100/50/miss)")

        # 4 aim error hist
        ax = axes[1][1]
        ax.hist(aims / radius, bins=40, color="#c9a", alpha=0.8)
        ax.axvline(1, color="#fff", ls="--", lw=1, label="1 circle radius")
        ax.set_title(f"Aim error (circle radii) mean={metrics['aim_px']['mean_norm']:.2f}  |  r={radius:.0f}px")
        ax.set_xlabel("distance from object center at keypress")
        ax.legend()
        plt.tight_layout()
        plt.savefig(f"{OUTDIR}/{tag}_charts.png", dpi=110)
        plt.close()

    # --- console summary ---
    print(f"=== {metrics['map']} ({tag}) ===")
    print(f"player={metrics['player']} mods={[k for k,v in metrics['mods'].items() if v]}")
    if map_version_mismatch:
        print("!! WARNING: replay ends before map's last object (failed play or version mismatch)", file=sys.stderr)
    print(f"acc={acc:.2%} max_combo={r.max_combo}  |  recorded 300/100/50/miss={recorded}  detected={detected}")
    print(f"whiffed presses (hit nothing): {whiffed_presses}")
    if ur:
        print(f"UR={ur:.1f}  mean_err={metrics['hit_error_ms']['mean']:+.1f}ms  std={metrics['hit_error_ms']['std']:.1f}ms  early={metrics['early_pct']:.0%}")
    if aims.size:
        print(f"aim: mean={metrics['aim_px']['mean']:.1f}px ({metrics['aim_px']['mean_norm']:.2f}r) p90={metrics['aim_px']['p90']:.1f}px")
    print("patterns:")
    for p, d in sorted(metrics["patterns"].items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {p:8s} n={d['n']:4d} miss={d['miss']:3d} ({d['miss_rate']:.1%})  "
              f"err={('%.1f' % d['mean_err']) if d['mean_err'] is not None else '--':>6}ms std={('%.1f' % d['std_err']) if d['std_err'] is not None else '--'}")
    print("regions:")
    for q, d in metrics["regions"].items():
        print(f"  {q} n={d['n']:4d} miss={d['miss']:3d} ({d['miss_rate']:.1%})  "
              f"mean_aim={d['mean_aim']:.1f}px" if d["mean_aim"] is not None
              else f"  {q} n={d['n']:4d} miss={d['miss']:3d} ({d['miss_rate']:.1%})  mean_aim=--")
    print("quarters (miss / mean_err / std):")
    for k, q in enumerate(metrics["quarters"]):
        print(f"  Q{k+1} n={q['n']:3d} miss={q['miss']:3d} err={q['mean_err'] and round(q['mean_err'],1)}ms std={q['std_err'] and round(q['std_err'],1)}ms")
    print(f"keys: {key_usage}  |  same-key adjacencies: {tap['same_key_pct']:.0%} (alt_ratio {tap['alt_ratio']:.0%})")
    print(f"streams: {len(stream_stats)} segments, worst 3 by std:")
    for s in sorted(stream_stats, key=lambda s: -(s['std_err'] or 0))[:3]:
        print(f"  t={s['t_start']:.0f}-{s['t_end']:.0f}ms n={s['n']} miss={s['miss']} "
              f"err={s['mean_err'] and round(s['mean_err'],1)}ms std={s['std_err'] and round(s['std_err'],1)}ms "
              f"alt={s['alt_ratio']:.0%} {s['key_pattern'][:30]}")
    print(f"json: {OUTDIR}/{tag}_metrics.json")


if __name__ == "__main__":
    main()
