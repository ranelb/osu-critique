"""Resolve replay (.osr) -> beatmap (.osu) pairs.

Every source uses the **same exact-matching rule**: a replay's ``beatmap_md5``
equals the raw MD5 of the .osu file bytes (this holds for osu!stable and
osu!lazer alike). Sources, all auto-detected / configurable:

- ``lazer``:    ``exports/*.osr`` + the content-addressed ``files/`` store
- ``stable``:   ``Replays/*.osr`` + ``Songs/**/*.osu``
- ``folders``:  ``./replays/*.osr`` + ``./maps/*.osu|*.osz`` (project folders)
"""
from __future__ import annotations

import glob
import hashlib
import os
import sys
import zipfile
from pathlib import Path

from ..config import (cache_dir, lazer_exports, lazer_files,
                      replays_dir as _replays_dir, maps_dir as _maps_dir,
                      stable_replays, stable_songs)


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _file_md5(path) -> str:
    with open(path, "rb") as f:
        return _md5(f.read())


# ------------------------------------------------------------ indexing ------

def index_osu_dir(directory) -> dict[str, str]:
    """md5 -> path for every .osu file under ``directory`` (recursive)."""
    idx = {}
    for p in glob.glob(os.path.join(str(directory), "**", "*.osu"), recursive=True):
        idx[_file_md5(p)] = p
    return idx


def build_lazer_index(files_dir) -> dict[str, str]:
    """md5 -> path for every .osu blob in lazer's content-addressed store.

    lazer stores beatmaps as extension-less files; the beatmap MD5 (as stored
    in .osr files) is the raw MD5 of the .osu file bytes.
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
            idx[_md5(raw)] = p
            n += 1
    print(f"indexed {n} .osu blobs (lazer store)", file=sys.stderr)
    return idx


def index_maps_folder(maps: Path, cache: Path) -> dict[str, str]:
    """md5 -> path for .osu files in ``maps``, extracting .osz archives.

    .osu files are indexed in place; .osz files are zip archives whose .osu
    contents are extracted to ``cache`` (deduped by content md5).
    """
    cache.mkdir(parents=True, exist_ok=True)
    idx = index_osu_dir(maps)
    n_osz = 0
    for osz in glob.glob(os.path.join(str(maps), "**", "*.osz"), recursive=True):
        try:
            with zipfile.ZipFile(osz) as z:
                for name in z.namelist():
                    if not name.endswith(".osu"):
                        continue
                    content = z.read(name)
                    m = _md5(content)
                    if m not in idx:
                        out = cache / f"{m}.osu"
                        if not out.exists():
                            out.write_bytes(content)
                        idx[m] = str(out)
                    n_osz += 1
        except zipfile.BadZipFile as e:
            print(f"!! bad .osz {osz}: {e}", file=sys.stderr)
    if n_osz:
        print(f"indexed {n_osz} .osu from .osz archives", file=sys.stderr)
    return idx


def _pair_by_md5(replays, index, label):
    """Pair replays to maps by md5; returns [(replay, map)]."""
    import slider as _slider
    pairs = []
    for rp in sorted(replays):
        r = _slider.Replay.from_path(rp, retrieve_beatmap=False)
        blob = index.get(r.beatmap_md5)
        if not blob:
            print(f"!! no map for {os.path.basename(rp)[:55]} "
                  f"(md5 {r.beatmap_md5[:12]}...)", file=sys.stderr)
            continue
        pairs.append((rp, blob))
    return pairs


# ------------------------------------------------------------- sources ------

def pair_lazer(exports_dir=None, files_dir=None):
    exports_dir = Path(exports_dir or lazer_exports())
    files_dir = Path(files_dir or lazer_files())
    replays = sorted(glob.glob(os.path.join(str(exports_dir), "*.osr")))
    if not replays:
        print(f"no lazer replays in {exports_dir}", file=sys.stderr)
        return []
    return _pair_by_md5(replays, build_lazer_index(files_dir), "lazer")


def pair_stable(replays_dir=None, songs_dir=None):
    root = stable_replays()
    if root is None:
        return []  # stable unsupported on this platform (Windows-only)
    replays_dir = Path(replays_dir or root)
    songs_dir = Path(songs_dir or stable_songs())
    replays = sorted(glob.glob(os.path.join(str(replays_dir), "*.osr")))
    if not replays:
        print(f"no stable replays in {replays_dir}", file=sys.stderr)
        return []
    return _pair_by_md5(replays, index_osu_dir(songs_dir), "stable")


def pair_folders(replays_dir=None, maps_dir=None, cache=None):
    replays_dir = Path(replays_dir or _replays_dir())
    maps_dir = Path(maps_dir or _maps_dir())
    cache = Path(cache or cache_dir())
    cache.mkdir(parents=True, exist_ok=True)
    replays = sorted(glob.glob(os.path.join(str(replays_dir), "**", "*.osr"),
                               recursive=True))
    if not replays:
        print(f"no replays in ./{replays_dir}", file=sys.stderr)
        return []
    return _pair_by_md5(replays, index_maps_folder(maps_dir, cache), "folders")


def pair_all():
    """Pair from every available source: [(source, replay, map)]."""
    seen = set()
    out = []
    for source, fn in (("lazer", pair_lazer), ("stable", pair_stable),
                       ("folders", pair_folders)):
        for rp, mp in fn():
            if rp in seen:
                continue
            seen.add(rp)
            out.append((source, rp, mp))
    return out
