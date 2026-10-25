#!/usr/bin/env python3
"""Generate a demo corpus for screenshots — fabricated plays on public maps.

The real corpus is the author's; screenshots of it cannot be published. This
writes a throwaway ``out/`` whose *map identity* is real (public osu! metadata
and cover art, fetched through the API with your own credentials) and whose
*plays are invented*: plausible accuracy/UR/miss numbers shaped by each map's
star rating, coherent per-object records, and a date spread that gives the
digest both history and a window.

Nothing here is evidence of anything. It exists so `docs/screenshots/` can show
the interface without leaking a player's history.

    python scripts/make_demo_corpus.py --out /tmp/oc-demo/out
    OSU_OUTDIR=/tmp/oc-demo/out osu-critique serve --port 8767

The output folder is self-contained: index built, digests written, covers
fetched lazily by the web layer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from osu_critique import digest, index  # noqa: E402
from osu_critique.config import osu_client_id, osu_client_secret  # noqa: E402
from osu_critique.io.beatmap import od_windows  # noqa: E402
from osu_critique.profile import _get_token  # noqa: E402

API = "https://osu.ppy.sh/api/v2"
PLAYER = "demo"


# ------------------------------------------------------------------- API ----

def _get(token: str, path: str, **params):
    import urllib.parse
    import urllib.request

    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=25))


def fetch_maps(count: int) -> list[dict]:
    token = _get_token(osu_client_id(), osu_client_secret())
    if not token:
        raise SystemExit("no osu! API credentials configured (osu-critique setup)")
    found = _get(token, "/beatmapsets/search", m=0, s="ranked",
                 sort="plays_desc", per_page=50)
    maps = []
    for s in found["beatmapsets"]:
        diffs = [b for b in s.get("beatmaps", []) if b.get("mode") == "osu"]
        if not diffs:
            continue
        beatmap = max(diffs, key=lambda b: b["difficulty_rating"])
        maps.append({
            "set_id": s["id"],
            "beatmap_id": beatmap["id"],
            "title": s["title"],
            "artist": s["artist"],
            "creator": s["creator"],
            "version": beatmap["version"],
            "sr": float(beatmap["difficulty_rating"]),
            "status": s.get("status"),
            "bpm": float(s.get("bpm") or 180.0),
        })
        if len(maps) >= count:
            break
    return maps


# -------------------------------------------------------------- fabrication --

def _h(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


FAMILIES = ("slider_1/2_jump", "circle_1/2_jump", "slider_1/4_dense",
            "circle_1/4_spaced", "circle_1/1_jump")
SHAPES = ("near-reversal chain", "cornered (box)", "flow (arc/line)")


def make_run(meta: dict, tag: str, replay_md5: str, when: datetime,
             skill: float, rng: random.Random, attempt: int = 0,
             weak: str | None = None, swing: str | None = None) -> tuple[dict, dict]:
    """One invented play: metrics doc + per-object record."""
    sr = meta["sr"]
    n_objects = int(_clamp(220 + sr * 55 + rng.randint(-40, 60), 180, 900))
    od = _clamp(8.4 + (sr - 5.0) * 0.25, 7.0, 9.6)
    cs = _clamp(3.6 + (sr - 5.0) * 0.22, 2.6, 4.8)
    mods = {"DT": False, "HT": False, "HD": False, "HR": False, "NF": False,
            "FL": False, "EZ": False, "RX": False, "AP": False}
    if rng.random() < 0.18:
        mods["HD"] = True
    if rng.random() < 0.10:
        mods["DT"] = True
    scale = 2.0 / 3.0 if mods["DT"] else 1.0
    mod_string = "+".join(k for k, v in mods.items() if v) or "NM"

    # aim for a believable performance: difficulty costs accuracy, skill helps
    base = 0.965 - (sr - 4.0) * 0.022 + (skill - 0.5) * 0.05
    base += rng.gauss(0, 0.012)
    acc = _clamp(base, 0.70, 0.995)
    miss_rate = _clamp(0.02 + (sr - 4.0) * 0.012 - (skill - 0.5) * 0.02, 0.0, 0.14)
    misses = int(round(n_objects * miss_rate * rng.uniform(0.5, 1.6)))
    hundred = int(round(n_objects * _clamp(0.14 - (acc - 0.85), 0.02, 0.2)
                        * rng.uniform(0.6, 1.2)))
    fifty = int(round(hundred * 0.18))
    n300 = max(0, n_objects - misses - hundred - fifty)
    acc = 100.0 * (6 * n300 + 2 * hundred + fifty) / (6 * n_objects) / 100.0
    # the rate a bucket has to beat to be "worse than the play itself"
    non300 = (n_objects - n300) / n_objects

    ur = _clamp(95 + (sr - 4.0) * 16 + rng.gauss(0, 12), 70, 320)
    err_std = ur / 10.0
    w300, w100, w50 = od_windows(od, scale)
    radius = 512.0 / 16.0 * (1.0 - 0.7 * (cs - 5.0) / 5.0)

    # per-object records: a wandering cursor path, notes on a steady beat
    gap = 60000.0 / meta["bpm"] / 4.0
    t0 = 9000.0 + rng.uniform(0, 3000)
    objects, misses_rows = [], []
    miss_at = set(rng.sample(range(10, n_objects - 10), min(misses, n_objects - 20))
                  if misses else [])
    x, y = rng.uniform(80, 430), rng.uniform(60, 320)
    for i in range(n_objects):
        t = t0 + i * gap * rng.uniform(0.97, 1.03)
        tx, ty = rng.uniform(20, 490), rng.uniform(20, 360)
        x += (tx - x) * rng.uniform(0.35, 0.85)
        y += (ty - y) * rng.uniform(0.35, 0.85)
        result = "300"
        if i in miss_at:
            result = "miss"
        elif rng.random() < hundred / n_objects * 1.4:
            result = "100"
        elif rng.random() < fifty / n_objects * 1.4:
            result = "50"
        err = None if result == "miss" else _clamp(rng.gauss(-4, err_std), -w50, w50)
        kind = "Slider" if rng.random() < 0.28 else "Circle"
        objects.append({
            "i": i, "t": round(t, 1), "end_t": round(t + (260 if kind == "Slider" else 0), 1),
            "x": round(_clamp(x, 0, 512), 1), "y": round(_clamp(y, 0, 384), 1),
            "kind": kind, "result": result,
            "pattern": rng.choice(["flow", "jump", "dense", "stream"]),
            "error_ms": None if err is None else round(err, 1),
            "key": rng.choice(["A", "B"]),
            "cursor_speed": round(abs(rng.gauss(0.7, 0.3)), 3),
            "aim_px": None if result == "miss" else round(abs(rng.gauss(radius * 0.4, radius * 0.18)), 2),
            "aim_r": None if result == "miss" else round(abs(rng.gauss(0.4, 0.18)), 3),
            "spacing_r": round(rng.uniform(1.2, 7.5), 2),
            "strain_aim": round(rng.uniform(0.2, 1.4), 2),
            "strain_speed": round(rng.uniform(0.2, 1.4), 2),
            "snap": rng.choice([2.0, 3.0, 4.0, 6.0]),
            "bpm": meta["bpm"], "bpm_eff": round(meta["bpm"] / scale, 1),
            "angle_deg": round(rng.uniform(0, 180), 1),
            "slider_tail_off": None, "slider_missed_ticks": None,
            "slider_off_pct": None,
        })
        if result == "miss":
            misses_rows.append({
                "i": i, "t": round(t, 1), "kind": kind,
                "d_r": round(rng.uniform(0.6, 2.2), 2),
                "closest_r": round(rng.uniform(0.2, 1.5), 2),
                "aim_at_press_r": round(rng.uniform(0.9, 2.0), 2),
                "press_ms": round(rng.gauss(-6, 18), 0),
                "key": rng.choice(["A", "B"]),
                "gap_r": round(rng.uniform(2.0, 9.0), 2),
                "turn_deg": round(rng.uniform(20, 175), 0),
                "speed": round(rng.uniform(0.2, 1.6), 2),
            })
    errs = [o["error_ms"] for o in objects if o["error_ms"] is not None]
    errs.sort()
    mean = sum(errs) / len(errs) if errs else 0.0
    std = math.sqrt(sum((e - mean) ** 2 for e in errs) / len(errs)) if errs else 0.0
    ur = round(std * 10.0, 1)

    segments = []
    for k in range(rng.randint(3, 7)):
        start = rng.randrange(5, max(6, n_objects - 20))
        n = rng.randint(8, 22)
        clean = rng.random() < 0.6
        t_start = objects[start]["t"]
        segments.append({
            "t_start": t_start, "t_end": objects[min(start + n, n_objects - 1)]["t"],
            "n": n, "miss": 0 if clean else rng.randint(1, 3),
            "mean_err": round(rng.gauss(-3, 4), 2), "std_err": round(rng.gauss(11, 3), 2),
            "gap_ms": round(gap, 1), "velocity_r_ms": round(rng.uniform(0.03, 0.09), 4),
            "notes_per_s": round(1000.0 / gap, 2), "alt_ratio": round(rng.uniform(0.8, 1.0), 2),
            "key_pattern": "ABAB", "kinds": {"Circle": n},
        })
    quarters = []
    step = n_objects // 4
    for q in range(4):
        chunk = objects[q * step:(q + 1) * step if q < 3 else n_objects]
        cerr = [o["error_ms"] for o in chunk if o["error_ms"] is not None]
        quarters.append({
            "range": [chunk[0]["t"], chunk[-1]["t"]], "n": len(chunk),
            "miss": sum(1 for o in chunk if o["result"] == "miss"),
            "mean_err": round(sum(cerr) / len(cerr), 2) if cerr else 0.0,
            "std_err": round(math.sqrt(sum((e - sum(cerr) / len(cerr)) ** 2 for e in cerr)
                                        / len(cerr)), 2) if cerr else 0.0,
        })

    composition = []
    for family, weight in (("slider_1/2_jump", 0.30), ("circle_1/2_jump", 0.24),
                           ("slider_1/4_dense", 0.16), ("circle_1/4_spaced", 0.12),
                           ("circle_1/1_jump", 0.10)):
        n = int(n_objects * weight)
        factor = rng.uniform(0.8, 1.1)
        if family == weak:
            factor = rng.uniform(2.0, 2.6)        # consistent weakness
        elif family == swing:
            factor = 2.4 if attempt % 2 == 0 else 0.25   # swings between attempts
        rate = _clamp(non300 * factor, 0.0, 0.75)
        composition.append({"family": family, "n": n, "share": weight,
                            "non300": int(n * rate), "non300_rate": round(rate, 3),
                            "mean_err_ms": round(rng.gauss(-4, 3), 1),
                            "std_err_ms": round(rng.gauss(12, 3), 1),
                            "mean_aim_r": round(rng.uniform(0.3, 0.6), 3),
                            "reported": True})
    shapes = []
    for cls, weight in (("near-reversal chain", 0.45), ("cornered (box)", 0.15),
                        ("flow (arc/line)", 0.40)):
        n = int(n_objects * weight)
        factor = rng.uniform(0.8, 1.15)
        if cls == weak:
            factor = rng.uniform(2.0, 2.6)
        elif cls == swing:
            factor = 2.4 if attempt % 2 == 0 else 0.25
        rate = _clamp(non300 * factor, 0.0, 0.75)
        shapes.append({"class": cls, "n": n, "share": weight,
                       "non300": int(n * rate), "non300_rate": round(rate, 3),
                       "mean_d_r": round(rng.uniform(0.3, 0.8), 3),
                       "mean_gap_r": round(rng.uniform(3, 8), 2), "reported": True})

    bias = round(rng.gauss(-5, 4), 1)
    aim_mean = round(abs(rng.gauss(0.42, 0.1)), 3)
    metrics = {
        "schema_version": 1,
        "tag": tag,
        "beatmap_md5": meta["md5"],
        "replay_md5": replay_md5,
        "played_at": when.isoformat(timespec="microseconds"),
        "player": PLAYER,
        "map": f'{meta["artist"]} - {meta["title"]} [{meta["version"]}]',
        "mods": mods,
        "mod_string": mod_string,
        "time_scale": scale,
        "windows_ms": {"300": round(w300, 1), "100": round(w100, 1), "50": round(w50, 1)},
        "time_base": {"overridden": False, "rows_scale": scale, "player_scale": scale,
                      "rows_to_player": 1.0,
                      "windows_ms_player": {"300": round(w300, 1), "100": round(w100, 1),
                                            "50": round(w50, 1)},
                      "note": None},
        "difficulty": {"CS": round(cs, 1), "AR": round(9.4, 1), "OD": round(od, 1),
                       "HP": 5.0},
        "counts_recorded": {"300": n300, "100": hundred, "50": fifty, "miss": misses},
        "counts_detected": {"300": n300, "100": hundred, "50": fifty, "miss": misses},
        "trust": {"count_deltas": {"300": 0, "100": 0, "50": 0, "miss": 0},
                  "abs_delta_total": 0, "abs_delta_pct": 0.0, "judged": n_objects,
                  "miss_tolerance": 3.5, "total_tolerance": 8.7,
                  "within_tolerance": True, "calibrated_scale": scale,
                  "mod_scale": scale, "scale_overridden": False,
                  "trustworthy": True, "notes": []},
        "profile": {"composition": composition,
                    "rate": {"effective_bpm": {"median": meta["bpm"], "min": meta["bpm"] - 4,
                                               "max": meta["bpm"] + 4},
                             "note_gap_ms": {"median": round(gap, 1)},
                             "gap_vs_300_window": {"median": round(gap / w300, 2)},
                             "reported": True},
                    "sliders": {"n": int(n_objects * 0.28)},
                    "stamina": {"peak": round(rng.uniform(4, 8), 1)},
                    "chains": {"n": 12, "notes": 90},
                    "timing_by_family": [], "context": []},
        "aim_mode": {"window_ms": 320.0, "sample_ms": 3.0, "n": n_objects,
                     "is_relax": False, "duration_s": round(n_objects * gap / 1000, 1),
                     "t_start_s": round(t0 / 1000, 1),
                     "distance_at_note_r": {"mean": round(aim_mean + 0.05, 3),
                                            "median": aim_mean, "p10": 0.1, "p90": 0.9,
                                            "inside_pct": 0.92},
                     "closest_approach_r": {"mean": 0.31, "median": 0.22, "p10": 0.05,
                                            "p90": 0.7, "inside_pct": 0.99,
                                            "never_inside": 0},
                     "peak_offset_ms": {"median": 8, "p10": -6, "p90": 22,
                                        "early_pct": 0.34, "late_pct": 0.62},
                     "window_entry_ms": {"mean": 40, "median": 30, "p10": 8, "p90": 80,
                                         "never_entered": 3},
                     "reached_not_on_time": {"n": int(n_objects * 0.15), "pct": 15.0},
                     "error_shape": {"along_r": {"median": 0.2, "p10": 0.02, "p90": 0.6},
                                     "lateral_r": {"median": 0.1, "p90": 0.3},
                                     "short_pct": 0.4, "past_pct": 0.35},
                     "ceiling": [], "by_jump_distance": [], "over_time": []},
        "autopsy": {"is_relax": False,
                    "shapes": {"classes": shapes, "corner_deg": 120, "sharp_deg": 150,
                               "min_n": 10, "window": 5},
                    "arrival_margin_r": {"max": 2.1, "median": 0.4, "p90": 1.1, "p95": 1.4,
                                         "p99": 1.8, "beyond_rim_pct": 0.12,
                                         "n": n_objects},
                    "press_vs_arrival_ms": {"median": -9, "p10": -25, "p90": 6,
                                            "pressed_before_arrival_pct": 0.63,
                                            "n": n_objects},
                    "stutter": {"pct": 6.5, "n": 11, "presses": n_objects,
                                "min_early_ms": 30, "threshold_r": 1.5},
                    "misses": {"n": len(misses_rows), "rows": misses_rows},
                    "legs": {"heading_err_deg": {"mean": 3.1, "median": 2.4, "p90": 7.2,
                                                 "max": 13.0},
                             "path_efficiency": {"median": 0.93, "p10": 0.8,
                                                 "below_70pct_pct": 0.03, "n": n_objects},
                             "n": n_objects}},
        "map_version_mismatch": False,
        "failed_play": False,
        "n_objects_map": n_objects,
        "whiffed_presses": int(round(n_objects * rng.uniform(0.01, 0.05))),
        "whiffs": {"n": int(round(n_objects * 0.03)), "rate": 0.03,
                   "mash": 4, "off_target": 3, "slider_head": 1, "lost": 0,
                   "after_end": 1, "off_target_mean_r": 1.2},
        "accuracy": round(acc, 4),
        "max_combo": int(n_objects * rng.uniform(0.4, 0.95)),
        "full_combo": False,
        "n_objects": n_objects,
        "hit_error_ms": {"mean": bias, "std": round(std, 1),
                         "p10": round(errs[int(0.1 * len(errs))], 1) if errs else None,
                         "p90": round(errs[int(0.9 * len(errs))], 1) if errs else None,
                         "abs_mean": round(sum(abs(e) for e in errs) / len(errs), 1) if errs else 0.0},
        "ur": ur,
        "ur_pct_of_300_window": round(ur / 10.0 / w300 * 100.0, 1),
        "early_pct": round(rng.uniform(0.45, 0.7), 2),
        "aim_px": {"mean": round(aim_mean * radius, 1), "p90": round(aim_mean * radius * 1.7, 1),
                   "mean_norm": aim_mean},
        "aim_vs_speed": {"n": n_objects, "slope_r_per_px_ms": 0.04, "r2": 0.05, "bins": []},
        "key_usage": {"A": n_objects // 2, "B": n_objects - n_objects // 2},
        "spacing_radius": round(radius, 2),
        "patterns": {"jump": {"n": 80, "miss_rate": 0.03, "miss": 2, "mean_err": -4.0,
                              "std_err": 12.0},
                     "stream": {"n": 60, "miss_rate": 0.02, "miss": 1, "mean_err": -2.0,
                                "std_err": 11.0},
                     "dense": {"n": 50, "miss_rate": 0.04, "miss": 2, "mean_err": -3.0,
                               "std_err": 13.0},
                     "first": {"n": 1, "miss_rate": 0.0, "miss": 0, "mean_err": 0.0,
                               "std_err": 0.0}},
        "regions": {"TL": {"n": n_objects // 4, "miss_rate": 0.03, "miss": 1, "mean_aim": 0.4},
                    "TR": {"n": n_objects // 4, "miss_rate": 0.02, "miss": 1, "mean_aim": 0.4},
                    "BL": {"n": n_objects // 4, "miss_rate": 0.04, "miss": 2, "mean_aim": 0.45},
                    "BR": {"n": n_objects // 4, "miss_rate": 0.03, "miss": 1, "mean_aim": 0.42}},
        "quarters": quarters,
        "sliders": {"n": int(n_objects * 0.28), "miss": 1, "tail_off": 2, "cut": 9,
                    "cut_pct": 8.0, "tick_missed": 3, "tick_missed_pct": 2.0,
                    "off_pct_median": 0.0, "follow_r": 2.2, "sample_ms": 4.0},
        "spinners": {"n": 0},
        "streams": {"n_segments": len(segments), "segments": segments,
                    "notes": sum(s["n"] for s in segments),
                    "misses": sum(s["miss"] for s in segments),
                    "gap_ms_median": round(gap, 1),
                    "notes_per_s_p50": round(1000.0 / gap, 2),
                    "notes_per_s_p90": round(1000.0 / gap * 1.05, 2),
                    "velocity_r_ms_p50": 0.05, "velocity_r_ms_p90": 0.07,
                    "kinds": {"Circle": 40, "Slider": 12}},
        "tapping": {"n": n_objects, "same_key_adjacent": 4, "same_key_pct": 0.02,
                    "alt_ratio": 0.97},
        "breakdown": {"knee": 2.4, "cliff": None,
                      "ramp": {"t0": 0, "t1": 0, "mid_t": 0, "n": 0, "miss": 0,
                               "speed": [], "spacing": [], "object_ids": []},
                      "reversal": {}, "speed_bins": [], "cascades": []},
    }
    objects_doc = {
        "schema_version": 1, "tag": tag, "player": PLAYER,
        "map": metrics["map"], "beatmap_md5": meta["md5"], "mod_string": mod_string,
        "counts_recorded": metrics["counts_recorded"],
        "counts_detected": metrics["counts_detected"],
        "trust": metrics["trust"], "objects": objects,
    }
    return metrics, objects_doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="/tmp/oc-demo/out", help="output folder")
    ap.add_argument("--maps", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--recent-days", type=int, default=8,
                    help="the digest window (runs newer than this are 'new')")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    metas = fetch_maps(args.maps)
    print(f"fetched {len(metas)} public maps", file=sys.stderr)
    conn = index.connect(out / index.DB_FILENAME)
    now = datetime.now()
    runs = 0
    stars, status, pp = {}, {}, {}
    for k, meta in enumerate(metas):
        meta["md5"] = _h("map", meta["set_id"])
        conn.execute(
            "INSERT OR REPLACE INTO beatmaps (beatmap_md5, beatmap_id, set_id, title, "
            "artist, creator, version, mode, metadata_missing, parsed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (meta["md5"], meta["beatmap_id"], meta["set_id"], meta["title"],
             meta["artist"], meta["creator"], meta["version"], 0, 0, now.isoformat()))
        # a per-map weakness so the cross-attempt block has something true to say
        weak = rng.choice(FAMILIES + SHAPES)
        swing = rng.choice([x for x in FAMILIES + SHAPES if x != weak])
        # some maps were played before the window (history), some only in it
        attempts = rng.choice([2, 3, 3, 4, 5, 6])
        for a in range(attempts):
            older = a < attempts - 1 and rng.random() < 0.55
            days = (rng.uniform(args.recent_days + 2, args.recent_days + 30) if older
                    else rng.uniform(0.2, args.recent_days))
            when = now - timedelta(days=days, hours=rng.uniform(0, 8))
            tag = f"demo_{k}_{a}"
            replay_md5 = _h("replay", k, a, args.seed)
            metrics, objects = make_run(meta, tag, replay_md5, when,
                                        skill=rng.uniform(0.25, 0.9), rng=rng,
                                        attempt=a, weak=weak, swing=swing)
            (out / f"{tag}_metrics.json").write_text(json.dumps(metrics, indent=1))
            (out / f"{tag}_objects.json").write_text(json.dumps(objects, indent=1))
            stars[meta["md5"]] = {"NM": meta["sr"], "DT": round(meta["sr"] * 1.32, 1)}
            status[str(meta["beatmap_id"])] = {"status": meta["status"], "stars": meta["sr"],
                                               "set_id": meta["set_id"], "ranked": 1}
            pp[replay_md5] = {"pp": round(55 * meta["sr"] ** 2 * metrics["accuracy"] ** 8, 1),
                              "stars": meta["sr"], "mods": metrics["mod_string"]}
            runs += 1
    conn.commit()
    conn.close()

    # the joins the index reads: stars / pp / ranked status (as `stars`, `pp`,
    # `status` would write them)
    for name, payload in (("stars_by_md5.json", stars), ("pp_by_replay.json", pp),
                          ("beatmap_status.json", status)):
        (out / name).write_text(json.dumps(payload, indent=1))

    stats = index.sweep(out, quiet=True)
    since = (now - timedelta(days=args.recent_days)).isoformat(timespec="seconds")
    doc = digest.build(outdir=out, since=since, ingest_first=False, write=True,
                       quiet=True)
    print(f"{runs} invented plays over {len(metas)} public maps; "
          f"index {stats['runs']} runs / {stats['beatmaps']} beatmaps; "
          f"digest {doc.get('path')} ({doc['n_runs']} new)", file=sys.stderr)
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
