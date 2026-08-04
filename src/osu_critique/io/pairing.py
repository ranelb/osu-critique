"""Resolve replay (.osr) -> beatmap (.osu) pairs.

Two sources are supported:

- ``danser``: replays in a folder, maps in a Songs/ library. Paired by
  difficulty name, then scored by how well the map's object count and duration
  match the replay's recorded judgement count and frame span (robust against
  same-named difficulties in different mapsets).
- ``lazer``: osu!lazer exports. Paired by exact beatmap MD5: the replay's
  beatmap_md5 equals the raw MD5 of the .osu file bytes, which is looked up in
  lazer's content-addressed file store. Exact, no ambiguity.
"""
from __future__ import annotations

import glob
import hashlib
import os
import sys
import re

import slider

from ..config import DANSER_REPLAYS, DANSER_SONGS, LAZER_EXPORTS, LAZER_FILES


# ---------------------------------------------------------------- danser ----

def difficulty_from_replay(name):
    m = re.search(r"\[([^\]]+)\]", name)
    return m.group(1) if m else None


def map_info(path):
    """Lightweight map descriptor for candidate scoring."""
    bm = slider.Beatmap.from_path(path)
    objs = bm.hit_objects()
    t0 = objs[0].time.total_seconds() * 1000
    t1 = objs[-1].time.total_seconds() * 1000
    return {"path": path, "title": bm.title, "version": bm.version,
            "n": len(objs), "t0": t0, "t1": t1}


def _replay_span_info(path):
    r = slider.Replay.from_path(path, retrieve_beatmap=False)
    acts = [(a.offset.total_seconds() * 1000) for a in r.actions]
    t1 = max(acts)
    total = r.count_300 + r.count_100 + r.count_50 + r.count_miss
    return {"total": total, "t1": t1}


def pair_danser(replays_dir=DANSER_REPLAYS, songs_dir=DANSER_SONGS):
    """Pair every .osr in replays_dir with the best-matching .osu in songs_dir."""
    pairs = []
    for rp in sorted(glob.glob(os.path.join(str(replays_dir), "*.osr"))):
        diff = difficulty_from_replay(os.path.basename(rp))
        if not diff:
            print(f"!! no difficulty in name: {rp}")
            continue
        ri = _replay_span_info(rp)
        candidates = []
        for folder in glob.glob(os.path.join(str(songs_dir), "*")):
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
        for c in candidates:
            c["score"] = abs(c["n"] - ri["total"]) * 10 + abs(c["t1"] - ri["t1"]) / 1000
        best = min(candidates, key=lambda c: c["score"])
        if best["score"] > 50:
            print(f"!! weak match for {os.path.basename(rp)[:60]} "
                  f"(best={best['title']} [{best['version']}] n={best['n']} vs replay {ri['total']})")
        pairs.append((rp, best["path"]))
    return pairs


# ----------------------------------------------------------------- lazer ----

def build_md5_index(files_dir=LAZER_FILES):
    """md5 -> path for every .osu blob in lazer's content-addressed store.

    osu!lazer stores beatmaps as extension-less files whose path is derived
    from the SHA-256 of the content; the *beatmap* MD5 (as stored in .osr
    files) is the raw MD5 of the .osu file bytes.
    """
    idx = {}
    n = 0
    for root, _, fnames in os.walk(str(files_dir)):
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
            idx[hashlib.md5(raw).hexdigest()] = p
            n += 1
    print(f"indexed {n} .osu blobs", file=sys.stderr)
    return idx


def pair_lazer(exports_dir=LAZER_EXPORTS, files_dir=LAZER_FILES):
    """Pair every exported .osr with its exact map blob by beatmap MD5."""
    import slider as _slider
    idx = build_md5_index(files_dir)
    pairs = []
    for rp in sorted(glob.glob(os.path.join(str(exports_dir), "*.osr"))):
        r = _slider.Replay.from_path(rp, retrieve_beatmap=False)
        blob = idx.get(r.beatmap_md5)
        if not blob:
            print(f"!! no blob for {os.path.basename(rp)[:55]} (md5 {r.beatmap_md5[:12]}...)")
            continue
        pairs.append((rp, blob))
    return pairs


def pair_all():
    """danser pairs, then lazer pairs."""
    return pair_danser() + pair_lazer()
