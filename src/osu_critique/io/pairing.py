"""Resolve replay (.osr) -> beatmap (.osu) pairs from osu!lazer exports.

Exported replays are paired by exact beatmap MD5: the replay's beatmap_md5
equals the raw MD5 of the .osu file bytes, which is looked up in lazer's
content-addressed file store. Exact, no ambiguity.
"""
from __future__ import annotations

import glob
import hashlib
import os
import sys


def build_md5_index(files_dir):
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


def pair_lazer(exports_dir=None, files_dir=None):
    """Pair every exported .osr with its exact map blob by beatmap MD5."""
    from ..config import LAZER_EXPORTS, LAZER_FILES
    exports_dir = exports_dir or LAZER_EXPORTS
    files_dir = files_dir or LAZER_FILES
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
