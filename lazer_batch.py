#!/usr/bin/env python3
"""Pair lazer exports/*.osr replays with maps from lazer's file store.
Pairing: raw md5 of each .osu blob == replay's beatmap_md5 (exact)."""
import os, sys, re, glob, json, subprocess, hashlib

OSU_DATA = os.path.expanduser("~/.var/app/sh.ppy.osu/data/osu")
FILES = os.path.join(OSU_DATA, "files")
EXPORTS = os.path.join(OSU_DATA, "exports")
HERE = os.path.dirname(os.path.abspath(__file__))
ANALYZE = os.path.join(HERE, "analyze.py")
PY = os.path.join(HERE, ".venv", "bin", "python")
TMP = os.path.join(HERE, "tmp_maps")
os.makedirs(TMP, exist_ok=True)


def build_md5_index():
    """md5 -> (path, title, version) for every .osu blob in the store."""
    idx, n = {}, 0
    for root, _, fnames in os.walk(FILES):
        for fn in fnames:
            p = os.path.join(root, fn)
            try:
                with open(p, "rb") as f:
                    head = f.read(32)
            except OSError:
                continue
            if not head.startswith(b"osu file format"):
                continue
            with open(p, "rb") as f:
                raw = f.read()
            md5 = hashlib.md5(raw).hexdigest()
            idx[md5] = p
            n += 1
    print(f"indexed {n} .osu blobs", file=sys.stderr)
    return idx


def main():
    idx = build_md5_index()
    import slider
    pairs = []
    for rp in sorted(glob.glob(os.path.join(EXPORTS, "*.osr"))):
        r = slider.Replay.from_path(rp, retrieve_beatmap=False)
        blob = idx.get(r.beatmap_md5)
        if not blob:
            print(f"!! no blob for {os.path.basename(rp)[:55]} (md5 {r.beatmap_md5[:12]}…)")
            continue
        local = os.path.join(TMP, r.beatmap_md5 + ".osu")
        if not os.path.exists(local):
            import shutil
            shutil.copyfile(blob, local)
        pairs.append((rp, local))
        print(f"paired: md5 {r.beatmap_md5[:12]}… {os.path.basename(rp)[:50]}")

    print(f"\npaired {len(pairs)} lazer replays\n")
    for i, (rp, mp) in enumerate(pairs):
        diff = re.search(r"\[([^\]]+)\]", os.path.basename(rp))
        d = re.sub(r"[^A-Za-z0-9_-]+", "_", diff.group(1)).strip("_")[:24] if diff else "run"
        tag = f"{i:02d}_{d}"
        print(f"### {tag}  ({os.path.basename(rp)[:60]})")
        subprocess.run([PY, ANALYZE, "--charts", rp, mp, tag])
        print()

    # aggregate table
    rows = []
    for f in sorted(glob.glob(os.path.join(HERE, "out", "*_metrics.json"))):
        with open(f) as fh:
            rows.append(json.load(fh))
    # exclude danser-tag runs? no - include all; sort by acc
    print("\n================ AGGREGATE (all runs) ================")
    print(f"{'map':<40} {'acc':>6} {'UR':>5} {'mean_ms':>7} {'early':>5} {'aim_r':>5} {'miss':>4} {'whiff':>5} {'keysA/B':>7}")
    for m in sorted(rows, key=lambda r: r["accuracy"]):
        h = m["hit_error_ms"]
        print(f"{m['map'][:40]:<40} {m['accuracy']*100:5.1f}% {m['ur']:5.1f} {h['mean']:+6.1f} "
              f"{m['early_pct']*100:4.0f}% {m['aim_px']['mean_norm']:5.2f} {m['counts_recorded']['miss']:4d} "
              f"{m['whiffed_presses']:5d} {m['key_usage']['A']}/{m['key_usage']['B']}")


if __name__ == "__main__":
    main()
