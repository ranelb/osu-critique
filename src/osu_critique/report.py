"""High-level analysis: replay + map -> metrics dict (JSON-serialisable).

``analyze()`` is the package's core API. It ports the validated pipeline:
frame building (time-sorted), press detection, greedy aim-validated assignment,
OD-window classification, time-scale auto-calibration (some lazer exports and
mod flags are misleading), pattern/region/quarter/stream/tapping stats, and
version/failed-play sanity flags.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

import slider as _slider  # noqa: F401  (re-exported for convenience; used by circle_radius)

from .io.beatmap import (build_objects, circle_radius, load_beatmap,
                         mod_scale, od_windows)
from .io.replay import build_frames, find_presses, load_replay
from .metrics.assignment import assign
from .metrics.patterns import add_pattern_labels, pattern_stats
from .metrics.sections import quarter_stats, region_stats
from .metrics.streams import stream_stats
from .metrics.tapping import key_usage, tapping_stats
from .config import DEFAULT_OUTDIR


def analyze(replay_path, map_path, tag="run", do_charts=False,
            outdir=None, hit_tol=1.0, console=True):
    """Analyze one replay against its map; returns the metrics dict.

    Writes ``{outdir}/{tag}_metrics.json`` and, if ``do_charts``, a PNG chart.
    """
    outdir = outdir or DEFAULT_OUTDIR

    r = load_replay(replay_path)
    bm = load_beatmap(map_path)
    r.beatmap = bm  # enables .hits/.accuracy (needs OD)

    frames = build_frames(r)
    times = np.array([f[0] for f in frames])
    presses = find_presses(frames)
    press_times = [p[0] for p in presses]
    radius = circle_radius(bm.cs())
    search_od = (200 - 10 * bm.od()) + 120  # 50-window + slack

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
                                            radius, search, hit_tol)
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

    add_pattern_labels(results, radius)
    patterns = pattern_stats(results)
    regions = region_stats(results)
    quarters = quarter_stats(results)

    sliders = [x for x in results if x["kind"] == "Slider"]
    slider_miss = sum(1 for x in sliders if x["result"] == "miss")
    segs = stream_stats(results)
    tap = tapping_stats(results)
    keys = key_usage(results)

    metrics = {
        "tag": tag,
        "player": r.player_name,
        "map": f"{bm.title} [{bm.version}]",
        "mods": {"DT": r.double_time, "HT": r.half_time, "HD": r.hidden,
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
        "key_usage": keys,
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
        "streams": {"n_segments": len(segs), "segments": segs},
        "tapping": tap,
    }

    outdir = os.fspath(outdir)
    os.makedirs(outdir, exist_ok=True)
    out_json = os.path.join(outdir, f"{tag}_metrics.json")
    with open(out_json, "w") as f:
        json.dump(metrics, f, indent=2, default=float)

    if do_charts and len(errs):
        from .charts import render_charts
        render_charts(results, errs, aims, w300, w100, w50, ur, radius, tag, outdir)

    if console:
        console_summary(metrics, out_json)
    return metrics


def console_summary(metrics, out_json=None):
    """Human-readable summary of a metrics dict (mirrors the original CLI output)."""
    acc = metrics["accuracy"]
    ur = metrics["ur"]
    recorded = metrics["counts_recorded"]
    detected = metrics["counts_detected"]
    tap = metrics["tapping"]
    key_usage = metrics["key_usage"]
    stream_stats = metrics["streams"]["segments"]

    print(f"=== {metrics['map']} ({metrics['tag']}) ===")
    print(f"player={metrics['player']} mods={[k for k, v in metrics['mods'].items() if v]}")
    if metrics.get("map_version_mismatch"):
        print("!! WARNING: replay ends before map's last object (failed play or version mismatch)", file=sys.stderr)
    print(f"acc={acc:.2%} max_combo={metrics['max_combo']}  |  recorded 300/100/50/miss={recorded}  detected={detected}")
    print(f"whiffed presses (hit nothing): {metrics['whiffed_presses']}")
    if ur:
        h = metrics["hit_error_ms"]
        print(f"UR={ur:.1f}  mean_err={h['mean']:+.1f}ms  std={h['std']:.1f}ms  early={metrics['early_pct']:.0%}")
    aim = metrics["aim_px"]
    if aim["mean"] is not None:
        print(f"aim: mean={aim['mean']:.1f}px ({aim['mean_norm']:.2f}r) p90={aim['p90']:.1f}px")
    print("patterns:")
    for p, d in sorted(metrics["patterns"].items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {p:8s} n={d['n']:4d} miss={d['miss']:3d} ({d['miss_rate']:.1%})  "
              f"err={('%.1f' % d['mean_err']) if d['mean_err'] is not None else '--':>6}ms "
              f"std={('%.1f' % d['std_err']) if d['std_err'] is not None else '--'}")
    print("regions:")
    for q, d in metrics["regions"].items():
        if d["mean_aim"] is not None:
            print(f"  {q} n={d['n']:4d} miss={d['miss']:3d} ({d['miss_rate']:.1%})  mean_aim={d['mean_aim']:.1f}px")
        else:
            print(f"  {q} n={d['n']:4d} miss={d['miss']:3d} ({d['miss_rate']:.1%})  mean_aim=--")
    print("quarters (miss / mean_err / std):")
    for k, q in enumerate(metrics["quarters"]):
        print(f"  Q{k + 1} n={q['n']:3d} miss={q['miss']:3d} "
              f"err={q['mean_err'] and round(q['mean_err'], 1)}ms std={q['std_err'] and round(q['std_err'], 1)}ms")
    print(f"keys: {key_usage}  |  same-key adjacencies: {tap['same_key_pct']:.0%} (alt_ratio {tap['alt_ratio']:.0%})")
    print(f"streams: {len(stream_stats)} segments, worst 3 by std:")
    for s in sorted(stream_stats, key=lambda s: -(s["std_err"] or 0))[:3]:
        print(f"  t={s['t_start']:.0f}-{s['t_end']:.0f}ms n={s['n']} miss={s['miss']} "
              f"err={s['mean_err'] and round(s['mean_err'], 1)}ms "
              f"std={s['std_err'] and round(s['std_err'], 1)}ms "
              f"alt={s['alt_ratio']:.0%} {s['key_pattern'][:30]}")
    if out_json:
        print(f"json: {out_json}")
