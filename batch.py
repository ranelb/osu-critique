#!/usr/bin/env python3
"""Batch: pair each replay in ~/Documents/Danser/Replays/ with its .osu map
in ~/Documents/Danser/Songs/ and run analyze.py --charts on each pair.
Pairing: match by difficulty name, then score candidates by how well the
map's object count and duration match the replay's recorded judgement
count and real frame span (robust against same-named diffs in other sets)."""
import os, re, glob, subprocess, sys, json
import slider

REPLAYS = os.path.expanduser("~/Documents/Danser/Replays")
SONGS = os.path.expanduser("~/Documents/Danser/Songs")
HERE = os.path.dirname(os.path.abspath(__file__))
ANALYZE = os.path.join(HERE, "analyze.py")
PY = os.path.join(HERE, ".venv", "bin", "python")


def difficulty_from_replay(name):
    m = re.search(r"\[([^\]]+)\]", name)
    return m.group(1) if m else None


def map_info(path):
    bm = slider.Beatmap.from_path(path)
    objs = bm.hit_objects()
    t0 = objs[0].time.total_seconds() * 1000
    t1 = objs[-1].time.total_seconds() * 1000
    return {"path": path, "title": bm.title, "version": bm.version,
            "n": len(objs), "t0": t0, "t1": t1}


def replay_info(path):
    r = slider.Replay.from_path(path, retrieve_beatmap=False)
    # real play span from the sorted action frames
    acts = [(a.offset.total_seconds() * 1000) for a in r.actions]
    t1 = max(acts)
    total = r.count_300 + r.count_100 + r.count_50 + r.count_miss
    return {"total": total, "t1": t1}


pairs = []
for rp in sorted(glob.glob(os.path.join(REPLAYS, "*.osr"))):
    diff = difficulty_from_replay(os.path.basename(rp))
    if not diff:
        print(f"!! no difficulty in name: {rp}")
        continue
    ri = replay_info(rp)
    # find all candidate .osu files with this difficulty name
    candidates = []
    for folder in glob.glob(os.path.join(SONGS, "*")):
        if not os.path.isdir(folder):
            continue
        for f in glob.glob(os.path.join(folder, "*.osu")):
            if f"[{diff}]" in os.path.basename(f):
                try:
                    candidates.append(map_info(f))
                except Exception as e:
                    print(f"!! parse failed {f}: {e}")
    if not candidates:
        print(f"!! no map for {os.path.basename(rp)}")
        continue
    # score: object-count match dominates, then duration proximity
    for c in candidates:
        c["score"] = abs(c["n"] - ri["total"]) * 10 + abs(c["t1"] - ri["t1"]) / 1000
    best = min(candidates, key=lambda c: c["score"])
    if best["score"] > 50:
        print(f"!! weak match for {os.path.basename(rp)[:60]} (best={best['title']} [{best['version']}] n={best['n']} vs replay {ri['total']})")
    pairs.append((rp, best["path"]))
    print(f"paired: {os.path.basename(rp)[:55]:<57} -> {best['title'][:30]} [{best['version']}] (n={best['n']})")

print(f"\npaired {len(pairs)} replay+map sets\n")

for rp, mp in pairs:
    diff = difficulty_from_replay(os.path.basename(rp))
    tag = re.sub(r"[^A-Za-z0-9_-]+", "_", diff).strip("_")[:40]
    print(f"### {tag}")
    subprocess.run([PY, ANALYZE, "--charts", rp, mp, tag])
    print()

# aggregate table
rows = []
for f in sorted(glob.glob(os.path.join(HERE, "out", "*_metrics.json"))):
    with open(f) as fh:
        rows.append(json.load(fh))
print("\n================ AGGREGATE ================")
print(f"{'map':<42} {'acc':>6} {'UR':>5} {'mean_ms':>7} {'early':>5} {'aim_r':>5} {'miss':>4} {'whiff':>5} {'keysA/B':>7}  flag")
for m in sorted(rows, key=lambda r: r["accuracy"]):
    h = m["hit_error_ms"]
    flag = "MISMATCH" if m.get("map_version_mismatch") else ("*" if m["counts_detected"]["miss"] > m["counts_recorded"]["miss"] + 5 else "")
    print(f"{m['map'][:42]:<42} {m['accuracy']*100:5.1f}% {m['ur']:5.1f} {h['mean']:+6.1f} "
          f"{m['early_pct']*100:4.0f}% {m['aim_px']['mean_norm']:5.2f} {m['counts_recorded']['miss']:4d} "
          f"{m['whiffed_presses']:5d} {m['key_usage']['A']}/{m['key_usage']['B']}  {flag}")
