"""Per-map features for every beatmap on disk: the recommendation candidate pool.

The analysis pipeline answers "what happened in this play". To answer "what
should I play next" the tool needs the other half: a description of maps it has
never seen a replay for. This module derives that from the ``.osu`` alone —
difficulty, timing, spacing buckets, how much of the map is sustained material,
how much of it turns back on itself — and stores it in the derived index.

Neither a replay nor a key is needed. The only optional dependency is
``rosu-pp`` (the ``[stars]`` extra) for the star rating; without it the scan
still runs and leaves ``sr`` NULL, which the gate in ``recommend.py`` treats as
"cannot rank this map" rather than as a zero.

Two deliberate non-choices:

- **Realm is not read.** ``client.realm`` has the online id and lazer's cached
  star rating, but nothing reads it from Python (the Rust tool is version-bound
  and does no difficulty calculation), and it never carries the spacing/flow
  features the scorer needs. Parsing the ``.osu`` is ~15 ms and works for the
  lazer store, ``stable``'s ``Songs`` and a plain folder alike.
- **Nothing here interprets a play.** There is no miss, no accuracy, no result.
  Every number is a property of the map.
"""
from __future__ import annotations

import hashlib
import json
import statistics as st
import sys
import time
import warnings
from collections import Counter
from pathlib import Path

from . import index, mapmeta
from .config import (cache_dir, lazer_files, maps_dir,
                     outdir as _default_outdir, stable_songs)
from .io import pairing
from .io.beatmap import build_objects, circle_radius
from .metrics import geometry, rhythm
from .metrics.patterns import add_pattern_labels
from .metrics.structure import annotate
from .metrics.streams import find_runs

#: bump when a feature's definition changes: rows are re-extracted on next scan
FEATURE_VERSION = 2   # 2: geometry + tempo block (metrics/geometry.py, rhythm.py)

#: angle boundaries for the flow/anti-flow split, in degrees
FLOW_DEG = 45.0
ANTI_FLOW_DEG = 135.0

# --------------------------------------------------------------- discovery --

def sources(extra=None) -> list[tuple[str, Path]]:
    """Every directory that may hold beatmaps: ``[(label, path), ...]``.

    An explicit ``extra`` (``library scan --source DIR``) **replaces** the
    auto-detected sources instead of adding to them: a caller who names a folder
    wants that folder, and a test fixture corpus must not drag in the real
    library.
    """
    if extra:
        return [(f"source:{Path(p).name}", Path(p)) for p in extra]
    found: list[tuple[str, Path]] = []
    try:
        files = lazer_files()
        if files and Path(files).is_dir():
            found.append(("lazer", Path(files)))
    except Exception as exc:                      # a missing install is not an error
        print(f"  ! lazer store unavailable: {exc}", file=sys.stderr)
    for label, getter in (("maps", maps_dir), ("stable", stable_songs)):
        try:
            path = getter()
            if path and Path(path).is_dir():
                found.append((label, Path(path)))
        except Exception:
            pass
    return found


def discover(extra=None, log=None) -> dict[str, str]:
    """``{beatmap_md5: path}`` for every ``.osu`` the scan can find.

    The lazer store is content-addressed and extension-less, so it needs the
    header sniff in :func:`pairing.build_lazer_index`; ordinary folders go
    through :func:`pairing.index_maps_folder`, which also unpacks ``.osz``.
    """
    log = log or (lambda *_a: None)
    found: dict[str, str] = {}
    for label, path in sources(extra):
        if label == "lazer":
            found.update(pairing.build_lazer_index(path))
        else:
            found.update(pairing.index_maps_folder(path, cache_dir() / "library_osz"))
        log(f"  {label}: {path}")
    return found


# ------------------------------------------------------------ feature block --

def _stars(path) -> float | None:
    """NM star rating through rosu-pp, or None when the extra is not installed."""
    from .metrics import difficulty as D
    try:
        Beatmap, Difficulty, _ = D._rosu()
    except RuntimeError:
        return None
    try:
        return round(float(Difficulty().calculate(Beatmap(path=str(path))).stars), 3)
    except Exception:                                # unparsable by rosu, not by us
        return None


def _median(values):
    return float(st.median(values)) if values else None


def _share(n, total):
    return round(float(n) / total, 4) if total else None


def extract(path, md5: str | None = None, want_sr: bool = True) -> dict:
    """All features of one ``.osu`` file, as a JSON-serialisable dict.

    Raises on an unreadable or unparsable map; the scan catches that per file.
    """
    path = Path(path)
    raw = path.read_bytes()
    md5 = md5 or hashlib.md5(raw).hexdigest()
    text = raw.decode("utf-8-sig", errors="replace")
    meta = mapmeta.parse_text(text)

    import slider
    bm = slider.Beatmap.from_path(path)
    mode = meta.get("mode")
    if mode is None:
        mode = int(bm.mode) if bm.mode is not None else 0
    mode = int(mode)

    radius = circle_radius(bm.cs())
    with warnings.catch_warnings():
        # degenerate slider curves divide by a zero length; the geometry those
        # objects produce is still usable, and a warning per map is not
        warnings.simplefilter("ignore", RuntimeWarning)
        objs = build_objects(bm, 1.0)
        add_pattern_labels(objs, radius)
        annotate(objs, bm, radius, 1.0)           # snap/bpm/angle/strains

    n = len(objs)
    if n == 0:
        raise ValueError("map has no hit objects")

    kinds = Counter(o["kind"] for o in objs)
    length_ms = float(objs[-1]["end"] - objs[0]["t"]) if n > 1 else 0.0
    bpms = [o["bpm"] for o in objs if o.get("bpm")]
    patterns = Counter(o["pattern"] for o in objs[1:])
    angles = [o["angle_deg"] for o in objs if o.get("angle_deg") is not None]
    strains_aim = [o["strain_aim"] for o in objs if o.get("strain_aim") is not None]
    strains_speed = [o["strain_speed"] for o in objs if o.get("strain_speed") is not None]
    svs = [o["sv"] for o in objs if o.get("sv") is not None]

    runs = find_runs(objs)
    in_run = {id(x) for run in runs for x, _prev, _gap, _vel in run}
    run_nps = []
    for run in runs:
        span = run[-1][0]["t"] - run[0][0]["t"]
        if span > 0:
            run_nps.append(1000.0 * (len(run) - 1) / span)

    segs = rhythm.tag(objs, geometry.classify(objs, radius))
    shape_sum = geometry.summarize(segs, n)
    by_label = {}
    for sg in segs:
        d = by_label.setdefault(sg["label"], {"segments": 0, "notes": 0})
        d["segments"] += 1
        d["notes"] += sg["n"]

    feats = {
        "beatmap_md5": md5,
        "map_path": str(path),
        "feature_version": FEATURE_VERSION,
        "set_id": meta.get("BeatmapSetID"),
        "beatmap_id": meta.get("BeatmapID"),
        "mode": mode,
        "title": meta.get("Title"),
        "artist": meta.get("Artist"),
        "creator": meta.get("Creator"),
        "version": meta.get("Version"),
        "sr": _stars(path) if want_sr else None,
        "bpm": _median([float(b) for b in bpms]),
        "length_ms": length_ms,
        "ar": float(bm.ar()),
        "od": float(bm.od()),
        "cs": float(bm.cs()),
        "hp": float(bm.hp()),
        "n_objects": n,
        "n_circles": kinds.get("Circle", 0),
        "n_sliders": kinds.get("Slider", 0),
        "n_spinners": kinds.get("Spinner", 0),
        "slider_ratio": _share(kinds.get("Slider", 0), n),
        "density": round(1000.0 * n / length_ms, 3) if length_ms > 0 else None,
        "dense_share": _share(patterns.get("dense", 0), n - 1),
        "stream_share": _share(patterns.get("stream", 0), n - 1),
        "jump_share": _share(patterns.get("jump", 0), n - 1),
        "bigjump_share": _share(patterns.get("bigjump", 0), n - 1),
        "anti_flow_share": _share(sum(1 for a in angles if a >= ANTI_FLOW_DEG), len(angles)),
        "flow_share": _share(sum(1 for a in angles if a <= FLOW_DEG), len(angles)),
        "kiai_share": _share(sum(1 for o in objs if o.get("kiai")), n),
        "strain_aim_max": round(max(strains_aim), 3) if strains_aim else None,
        "strain_speed_max": round(max(strains_speed), 3) if strains_speed else None,
        # sustained material: the detector's own answer, not a re-derivation
        "sustained_share": _share(len(in_run), n),
        "sustained_max": max((len(r) for r in runs), default=0),
        "sustained_nps": _median(run_nps),
        "patterns": dict(patterns),
        # what the runs of notes are: shape x tempo (unlabelled is a valid answer)
        "geometry": {"coverage": round(shape_sum["coverage"], 4),
                     "shapes": shape_sum["shapes"], "labels": by_label},
        "angles": {
            "flow": sum(1 for a in angles if a <= FLOW_DEG),
            "anti": sum(1 for a in angles if a >= ANTI_FLOW_DEG),
            "n": len(angles),
        },
        "sv_min": round(min(svs), 3) if svs else None,
        "sv_max": round(max(svs), 3) if svs else None,
        "bpm_min": round(min(bpms), 2) if bpms else None,
        "bpm_max": round(max(bpms), 2) if bpms else None,
        "strain_aim_p90": round(_pct(strains_aim, 90), 3) if strains_aim else None,
        "strain_speed_p90": round(_pct(strains_speed, 90), 3) if strains_speed else None,
    }
    return feats


def _pct(values, pct):
    ordered = sorted(values)
    i = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[i]


#: columns of ``library_beatmaps`` filled from a feature dict (rest go to JSON)
ROW_COLUMNS = (
    "beatmap_md5", "map_path", "feature_version", "set_id", "beatmap_id", "mode",
    "title", "artist", "creator", "version", "sr", "bpm", "length_ms",
    "ar", "od", "cs", "hp", "n_objects", "n_circles", "n_sliders", "n_spinners",
    "slider_ratio", "density", "dense_share", "stream_share", "jump_share",
    "bigjump_share", "anti_flow_share", "flow_share", "kiai_share",
    "strain_aim_max", "strain_speed_max",
    "sustained_share", "sustained_max", "sustained_nps",
)


def to_row(feats: dict) -> dict:
    """Flatten a feature dict into the table's columns (long tail stays JSON)."""
    row = {c: feats.get(c) for c in ROW_COLUMNS}
    row["features_json"] = json.dumps(feats, default=float, sort_keys=True)
    return row


# ------------------------------------------------------------------ the scan --

def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def scan(outdir=None, extra_sources=None, rebuild: bool = False,
         want_sr: bool = True, quiet: bool = False, log=None) -> dict:
    """Bring ``library_beatmaps`` in line with the maps on disk.

    Incremental by (path, mtime, size, FEATURE_VERSION): an unchanged map is not
    re-parsed, so a rescan after a new import costs the walk plus the new maps.
    Rows whose file disappeared are dropped — this table is derived, and a map
    you deleted cannot be recommended.
    """
    out = Path(outdir or _default_outdir())
    started = time.time()
    conn = index.connect(index.db_path(out))
    stats = {"maps": 0, "added": 0, "updated": 0, "unchanged": 0,
             "removed": 0, "failed": 0, "no_sr": 0, "seconds": 0.0}
    say = log or (lambda msg: None if quiet else print(msg, file=sys.stderr))
    try:
        if rebuild:
            conn.execute("DELETE FROM library_beatmaps")
            conn.commit()
        known = {r["map_path"]: r for r in conn.execute(
            "SELECT map_path, beatmap_md5, mtime, size, feature_version "
            "FROM library_beatmaps")}
        found = discover(extra_sources, log=say)
        seen_md5 = set()
        for i, (md5, path) in enumerate(sorted(found.items()), 1):
            try:
                stt = Path(path).stat()
            except OSError:
                continue
            prev = known.get(str(path))
            if (prev is not None and not rebuild
                    and prev["feature_version"] == FEATURE_VERSION
                    and prev["mtime"] == stt.st_mtime
                    and prev["size"] == stt.st_size):
                stats["unchanged"] += 1
                seen_md5.add(prev["beatmap_md5"])
                continue
            try:
                feats = extract(path, md5=md5, want_sr=want_sr)
            except Exception as exc:                  # noqa: BLE001 - per file
                stats["failed"] += 1
                say(f"  ! {Path(path).name[:40]}: {type(exc).__name__}: {exc}")
                continue
            if feats.get("sr") is None:
                stats["no_sr"] += 1
            upsert(conn, feats, mtime=stt.st_mtime, size=stt.st_size)
            stats["added" if prev is None else "updated"] += 1
            seen_md5.add(md5)
            if not quiet and i % 500 == 0:
                say(f"  scanned {i}/{len(found)}...")
        # derived: a path that vanished is not a candidate any more
        for path, row in known.items():
            if row["beatmap_md5"] in seen_md5:
                continue
            conn.execute("DELETE FROM library_beatmaps WHERE beatmap_md5 = ?",
                         (row["beatmap_md5"],))
            stats["removed"] += 1
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('library_scanned_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (_now(),))
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('library_feature_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(FEATURE_VERSION),))
        conn.commit()
        stats["maps"] = conn.execute(
            "SELECT COUNT(*) FROM library_beatmaps").fetchone()[0]
        stats["seconds"] = round(time.time() - started, 1)
        return stats
    finally:
        conn.close()


def upsert(conn, feats: dict, mtime=None, size=None) -> dict:
    """Insert/replace one map's row from a feature dict (what the scan calls)."""
    row = to_row(feats)
    row["mtime"] = mtime
    row["size"] = size
    row["parsed_at"] = _now()
    _upsert(conn, row)
    return row


_INSERT_SQL = None


def _upsert(conn, row: dict) -> None:
    global _INSERT_SQL
    cols = list(row)
    if _INSERT_SQL is None or set(cols) != set(_INSERT_SQL[1]):
        _INSERT_SQL = (f"INSERT OR REPLACE INTO library_beatmaps ({', '.join(cols)}) "
                       f"VALUES ({', '.join('?' * len(cols))})", tuple(cols))
    conn.execute(_INSERT_SQL[0], [row[c] for c in _INSERT_SQL[1]])


# --------------------------------------------------------- status enrichment --

def enrich_status(conn, outdir, log=None) -> dict:
    """Fill ``rank_status`` from the osu! API for maps that carry a BeatmapID.

    Opt-in (``library scan --status``) because it is the only part of this
    module that touches the network. Shares ``out/beatmap_status.json`` with
    ``osu-critique status``, so a play and a candidate never disagree.
    """
    from .io import status as S
    say = log or print
    out = Path(outdir)
    cache_path = out / "beatmap_status.json"
    cache = {int(k): v for k, v in S._load_json(str(cache_path)).items()}
    rows = conn.execute(
        "SELECT beatmap_md5, beatmap_id FROM library_beatmaps "
        "WHERE beatmap_id IS NOT NULL").fetchall()
    missing = sorted({r["beatmap_id"] for r in rows if r["beatmap_id"] not in cache})
    fetched = 0
    if missing:
        from .config import osu_client_id, osu_client_secret
        from .profile import _get_token
        cid, secret = osu_client_id(), osu_client_secret()
        if not cid or not secret:
            raise RuntimeError(
                "no osu! API credentials for --status; create a client at "
                "https://osu.ppy.sh/oauth/clients and run `osu-critique setup` "
                f"(would query {len(missing)} beatmaps)")
        cache.update(S.fetch_statuses(missing, _get_token(cid, secret), log=say))
        S.save(cache, str(cache_path))
        fetched = len(missing)
    known = 0
    for r in rows:
        rec = cache.get(r["beatmap_id"])
        status = (rec or {}).get("status")
        conn.execute(
            "UPDATE library_beatmaps SET rank_status = ?, status_checked = ? "
            "WHERE beatmap_md5 = ?", (status, _now(), r["beatmap_md5"]))
        if status:
            known += 1
    conn.commit()
    return {"fetched": fetched, "known": known, "rows": len(rows)}


# ----------------------------------------------------------------- queries --

def rows(conn) -> list:
    """Every candidate row (the scorer filters in Python, not in SQL)."""
    return conn.execute(
        "SELECT * FROM library_beatmaps WHERE mode = 0").fetchall()


def features(row) -> dict:
    """The full feature dict of a row (columns are a subset of the JSON)."""
    try:
        return json.loads(row["features_json"] or "{}")
    except (ValueError, TypeError, IndexError):
        return {}


def summary(conn) -> dict | None:
    """What the scan currently covers; None when the scan never ran."""
    try:
        marker = conn.execute(
            "SELECT value FROM meta WHERE key = 'library_scanned_at'").fetchone()
        n = conn.execute("SELECT COUNT(*) FROM library_beatmaps").fetchone()[0]
    except Exception:
        return None
    if not marker or not n:
        return None
    no_sr = conn.execute(
        "SELECT COUNT(*) FROM library_beatmaps WHERE sr IS NULL").fetchone()[0]
    return {"scanned_at": marker["value"], "maps": n, "no_sr": no_sr,
            "feature_version": FEATURE_VERSION}
