"""SQLite index of the analysis corpus.

``out/`` stays the source of truth: every row here is a projection of an
``out/<tag>_metrics.json`` that can be rebuilt at any time. The web frontend
queries this because a listing page must not parse 3 000 JSON files, and the
map page needs "every attempt of this map" without a directory scan.

What the index deliberately does **not** hold: the per-object records and the
heavy metric blocks (``autopsy``, ``aim_mode``, ``breakdown``, ``profile``,
``regions``, ``quarters``, ``patterns``, ``streams``, ``sliders``). Those stay
in the JSON artifact and are read on demand for exactly one run. Adding an
``objects`` table later is additive; it is not a migration.

Authored data (annotations, critiques) is *not* derived — it lives in
canonical sidecar files under ``out/annotations/`` and ``out/critiques/`` and
is mirrored into these tables. Deleting the DB loses nothing.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import mapmeta
from .config import outdir as _default_outdir

DB_FILENAME = "index.sqlite"


class SchemaMismatch(RuntimeError):
    """The DB was written by another build; it is derived, so rebuild it."""
SCHEMA_VERSION = 4  # v4: critiques keyed by run_id (authored files, not rowids)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- one row per analysed replay artifact; a projection, not a copy of the doc.
-- The key is the artifact path, not the replay md5: re-exports of one play
-- exist (36 of them in the author's corpus) and dropping them silently would
-- violate the tool's "drop nothing" rule. run_id is the query key (the replay
-- md5, or "tag:<tag>" for pre-schema artifacts) and is not unique.
CREATE TABLE IF NOT EXISTS runs (
    json_path            TEXT PRIMARY KEY,
    run_id               TEXT NOT NULL,
    replay_md5           TEXT,
    tag                  TEXT NOT NULL,
    beatmap_md5          TEXT NOT NULL,     -- "" for the 4 pre-schema artifacts
    schema_version       INTEGER,           -- NULL for the pre-schema artifacts
    player               TEXT,
    played_at            TEXT,
    map_name             TEXT,
    mod_string           TEXT,
    mods_json            TEXT,
    time_scale           REAL,
    od                   REAL,
    ar                   REAL,
    cs                   REAL,
    hp                   REAL,
    n_objects            INTEGER,
    n_objects_map        INTEGER,
    accuracy             REAL,
    max_combo            INTEGER,
    full_combo           INTEGER,
    ur                   REAL,
    ur_pct_of_300        REAL,
    hit_error_mean       REAL,
    hit_error_std        REAL,
    hit_error_p10        REAL,
    hit_error_p90        REAL,
    whiffed_presses      INTEGER,
    counts_recorded_json TEXT,
    counts_detected_json TEXT,
    trust_ok             INTEGER,   -- 1 = trust.trustworthy
    trust_delta          INTEGER,   -- trust.abs_delta_total
    trust_judged         INTEGER,
    failed               INTEGER,   -- failed_play
    is_relax             INTEGER,   -- mods.RX, mods.AP, or aim_mode.is_relax
    time_base_overridden INTEGER,
    sr                   REAL,      -- joined from stars_by_md5.json
    pp                   REAL,      -- joined from pp_by_replay.json
    rank_status          TEXT,      -- joined from beatmap_status.json
    objects_path         TEXT,
    objects_missing      INTEGER NOT NULL DEFAULT 0,
    replay_path          TEXT,      -- for a future renderer; may be NULL
    map_path             TEXT,      -- path used at analysis time; may be NULL
    mtime                REAL,
    size                 INTEGER,
    indexed_at           TEXT
);

CREATE INDEX IF NOT EXISTS runs_by_map    ON runs (beatmap_md5, played_at);
CREATE INDEX IF NOT EXISTS runs_by_date   ON runs (played_at);
CREATE INDEX IF NOT EXISTS runs_by_run_id ON runs (run_id);

-- one row per beatmap; metadata is parsed from the .osu, best-effort
CREATE TABLE IF NOT EXISTS beatmaps (
    beatmap_md5      TEXT PRIMARY KEY,
    map_path         TEXT,      -- where the .osu was found (resolution cache)
    beatmap_id       INTEGER,
    set_id           INTEGER,
    title            TEXT,
    title_unicode    TEXT,
    artist           TEXT,
    artist_unicode   TEXT,
    creator          TEXT,
    version          TEXT,
    source           TEXT,
    tags             TEXT,
    background       TEXT,      -- filename from [Events]
    audio            TEXT,
    mode             INTEGER,
    metadata_missing INTEGER NOT NULL DEFAULT 0,
    cover_path       TEXT,      -- cached cover on disk, NULL until fetched
    cover_fetched_at TEXT,
    parsed_at        TEXT
);

-- authored, canonical in out/annotations/<beatmap_md5>.json
CREATE TABLE IF NOT EXISTS annotations (
    note_id     TEXT PRIMARY KEY,   -- minted by the sidecar, not a rowid
    scope       TEXT NOT NULL CHECK (scope IN ('map', 'run')),
    beatmap_md5 TEXT NOT NULL,
    replay_md5  TEXT,
    t_map       REAL,           -- NULL = general comment; map time (seconds)
    body        TEXT NOT NULL,
    tags        TEXT,           -- comma-separated
    created_at  TEXT NOT NULL,
    updated_at  TEXT,
    source_path TEXT            -- the sidecar it came from
);

CREATE INDEX IF NOT EXISTS annotations_by_map ON annotations (beatmap_md5);
CREATE INDEX IF NOT EXISTS annotations_by_run ON annotations (replay_md5);

-- authored, canonical in out/critiques/<run_id>.json
CREATE TABLE IF NOT EXISTS critiques (
    run_id      TEXT PRIMARY KEY,
    replay_md5  TEXT,
    beatmap_md5 TEXT,
    model       TEXT,
    prompt_hash TEXT,
    run_hash    TEXT,
    created     TEXT,
    body        TEXT NOT NULL,
    source_path TEXT
);
"""


# ------------------------------------------------------------------ helpers --

def db_path(outdir=None) -> Path:
    """``<outdir>/index.sqlite``; an explicit ``.sqlite`` path is passed through."""
    raw = Path(outdir or _default_outdir())
    return raw if raw.suffix == ".sqlite" else raw / DB_FILENAME


def connect(path) -> sqlite3.Connection:
    """Open (creating if needed) the index with the schema applied.

    WAL because the CLI writes while the web server reads; a read-only
    filesystem degrades to a memory-less error, which callers treat as
    "no index" rather than a crash.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(os.fspath(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                     (str(SCHEMA_VERSION),))
    elif int(row["value"]) != SCHEMA_VERSION:
        raise SchemaMismatch(
            f"index schema is v{row['value']}, this build expects v{SCHEMA_VERSION}; "
            "run `osu-critique index --rebuild`")
    conn.commit()


def _now() -> str:
    """Naive local time: it is compared with ``played_at`` (also naive local)
    and with the digest markers, so mixing in an offset would sort wrongly."""
    return datetime.now().isoformat(timespec="seconds")


def _json_or_none(value):
    return json.dumps(value, default=float) if value is not None else None


def _get(doc: dict, *path, default=None):
    """Nested lookup: ``_get(d, "trust", "trustworthy", default=False)``."""
    cur = doc
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return default if cur is None else cur


# ------------------------------------------------------------- row mapping --

def run_id_for(metrics: dict) -> str:
    """Stable key for a run: the replay md5, else a tag-derived fallback.

    Older artifacts can lack ``replay_md5``. Falling back to the tag keeps the
    index working instead of dropping the run; the column stays NULL so
    callers can tell the difference.
    """
    md5 = metrics.get("replay_md5")
    if md5:
        return md5
    return "tag:" + str(metrics.get("tag") or "run")


def metrics_to_row(metrics: dict, json_path, objects_path=None,
                   replay_path=None, map_path=None, mtime=None, size=None) -> dict:
    """Flatten the listing/filter scalars out of a metrics doc."""
    he = metrics.get("hit_error_ms") or {}
    tb = metrics.get("time_base") or {}
    trust = metrics.get("trust") or {}
    mods = metrics.get("mods") or {}
    row = {
        "run_id": run_id_for(metrics),
        "replay_md5": metrics.get("replay_md5"),
        "tag": metrics.get("tag") or "run",
        "beatmap_md5": metrics.get("beatmap_md5") or "",
        "schema_version": metrics.get("schema_version"),
        "player": metrics.get("player"),
        "played_at": metrics.get("played_at"),
        "map_name": metrics.get("map"),
        "mod_string": metrics.get("mod_string"),
        "mods_json": _json_or_none(mods),
        "time_scale": metrics.get("time_scale"),
        "od": _get(metrics, "difficulty", "OD"),
        "ar": _get(metrics, "difficulty", "AR"),
        "cs": _get(metrics, "difficulty", "CS"),
        "hp": _get(metrics, "difficulty", "HP"),
        "n_objects": metrics.get("n_objects"),
        "n_objects_map": metrics.get("n_objects_map"),
        "accuracy": metrics.get("accuracy"),
        "max_combo": metrics.get("max_combo"),
        "full_combo": 1 if metrics.get("full_combo") else 0,
        "ur": metrics.get("ur"),
        "ur_pct_of_300": metrics.get("ur_pct_of_300_window"),
        "hit_error_mean": he.get("mean"),
        "hit_error_std": he.get("std"),
        "hit_error_p10": he.get("p10"),
        "hit_error_p90": he.get("p90"),
        "whiffed_presses": metrics.get("whiffed_presses"),
        "counts_recorded_json": _json_or_none(metrics.get("counts_recorded")),
        "counts_detected_json": _json_or_none(metrics.get("counts_detected")),
        "trust_ok": 1 if trust.get("trustworthy") else 0,
        "trust_delta": trust.get("abs_delta_total"),
        "trust_judged": trust.get("judged"),
        "failed": 1 if metrics.get("failed_play") else 0,
        # AP (autoplay) is a Relax-like run without the RX flag; aim_mode knows.
        "is_relax": 1 if (mods.get("RX") or mods.get("AP")
                          or _get(metrics, "aim_mode", "is_relax", default=False))
                    else 0,
        "time_base_overridden": 1 if tb.get("overridden") else 0,
        # absolute, always: the same artifact must not get two rows because the
        # CLI ran from the repo (``out/x``) and the service from anywhere
        # (``/home/.../out/x``). This bit the systemd unit on first boot.
        "json_path": os.path.abspath(os.fspath(json_path)) if json_path else None,
        "objects_path": os.path.abspath(os.fspath(objects_path)) if objects_path else None,
        "objects_missing": 0 if objects_path and os.path.isfile(objects_path) else 1,
        "replay_path": os.path.abspath(os.fspath(replay_path)) if replay_path else None,
        "map_path": os.path.abspath(os.fspath(map_path)) if map_path else None,
        "mtime": mtime,
        "size": size,
        "indexed_at": _now(),
    }
    return row


# ------------------------------------------------------------ cache joins --

def _load_json(path):
    try:
        with open(path) as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def load_joins(outdir) -> dict:
    """The three existing cache files, loaded once per sweep.

    Missing or malformed caches are empty dicts: a missing ``stars`` cache is
    not an error, it is a NULL column.
    """
    root = Path(outdir)
    return {
        "stars": _load_json(root / "stars_by_md5.json"),
        "pp": _load_json(root / "pp_by_replay.json"),
        "status": _load_json(root / "beatmap_status.json"),
    }


def _join_values(row: dict, joins: dict, beatmap_id) -> dict:
    md5 = row["beatmap_md5"]
    per_mod = joins["stars"].get(md5) or {}
    sr = per_mod.get(row["mod_string"]) or per_mod.get("NM")
    pp_entry = joins["pp"].get(row["replay_md5"] or "") or {}
    status_entry = joins["status"].get(str(beatmap_id)) if beatmap_id else None
    return {
        "sr": sr,
        "pp": pp_entry.get("pp"),
        "rank_status": (status_entry or {}).get("status"),
    }


# ------------------------------------------------------- beatmap resolution --

class _MapResolver:
    """Find the ``.osu`` for a beatmap md5, building the pairing index at most
    once per sweep.

    The lazer content store is content-addressed and ~9 GB, so the scan costs
    tens of seconds. Caching the resolved path in the ``beatmaps`` table means
    an incremental sweep never pays it.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._index = None
        self._known = {
            r["beatmap_md5"]: r["map_path"]
            for r in conn.execute("SELECT beatmap_md5, map_path FROM beatmaps")
            if r["map_path"]
        }

    def _build(self):
        if self._index is not None:
            return self._index
        from .io import pairing
        self._index = {}
        try:
            from .config import lazer_files
            files = lazer_files()
            if files and Path(files).is_dir():
                self._index.update(pairing.build_lazer_index(files))
        except Exception as exc:  # a missing lazer install must not kill the index
            print(f"  ! lazer store unavailable: {exc}", file=sys.stderr)
        try:
            from .config import maps_dir
            maps = Path(maps_dir())
            if maps.is_dir():
                self._index.update(pairing.index_osu_dir(maps))
        except Exception:
            pass
        return self._index

    def resolve(self, beatmap_md5: str, hint=None):
        """Return a path to the .osu, or None."""
        for candidate in (hint, self._known.get(beatmap_md5)):
            if candidate and os.path.isfile(candidate):
                self._known[beatmap_md5] = candidate
                return os.fspath(candidate)
        found = self._build().get(beatmap_md5)
        if found:
            self._known[beatmap_md5] = found
        return found


def _upsert_beatmap(conn, beatmap_md5: str, map_path=None, resolver=None,
                    force: bool = False) -> int:
    """Insert or refresh the beatmaps row; returns the beatmap id (or None).

    Metadata is parsed once per (md5, path). A row that already has metadata
    and whose file still exists is left alone unless ``force``.
    """
    existing = conn.execute(
        "SELECT * FROM beatmaps WHERE beatmap_md5 = ?", (beatmap_md5,)).fetchone()
    if existing is not None and not force:
        cached = existing["map_path"]
        if existing["metadata_missing"] == 0 and cached and os.path.isfile(cached):
            return existing["beatmap_id"]
    path = map_path
    if resolver is not None:
        path = resolver.resolve(beatmap_md5, hint=map_path) or path
    if not path or not os.path.isfile(path):
        if existing is None:
            conn.execute(
                "INSERT INTO beatmaps (beatmap_md5, map_path, metadata_missing, parsed_at) "
                "VALUES (?, ?, 1, ?)", (beatmap_md5, path, _now()))
            return None
        # no .osu on disk, but the row may already carry metadata (a demo
        # corpus, or a map file that moved): keep its id so joins still work
        if not existing["metadata_missing"] and existing["beatmap_id"]:
            return existing["beatmap_id"]
        return None

    meta = mapmeta.parse_file(path)
    missing = 0 if (meta.get("Title") or meta.get("Version")) else 1
    values = {
        "map_path": os.fspath(path),
        "beatmap_id": meta.get("BeatmapID"),
        "set_id": meta.get("BeatmapSetID"),
        "title": meta.get("Title"),
        "title_unicode": meta.get("TitleUnicode"),
        "artist": meta.get("Artist"),
        "artist_unicode": meta.get("ArtistUnicode"),
        "creator": meta.get("Creator"),
        "version": meta.get("Version"),
        "source": meta.get("Source"),
        "tags": meta.get("Tags"),
        "background": meta.get("background"),
        "audio": meta.get("audio"),
        "mode": meta.get("mode"),
        "metadata_missing": missing,
        "parsed_at": _now(),
    }
    cols = ", ".join(f"{k} = ?" for k in values)
    if existing is None:
        keys = ", ".join(["beatmap_md5", *values])
        marks = ", ".join("?" * (len(values) + 1))
        conn.execute(f"INSERT INTO beatmaps ({keys}) VALUES ({marks})",
                     (beatmap_md5, *values.values()))
    else:
        conn.execute(f"UPDATE beatmaps SET {cols} WHERE beatmap_md5 = ?",
                     (*values.values(), beatmap_md5))
    return values["beatmap_id"]


# --------------------------------------------------------------- upserting --

_RUN_COLUMNS = None  # replaced by _run_columns(conn): the schema is the list


def _run_columns(conn) -> list[str]:
    return [r["name"] for r in conn.execute("PRAGMA table_info(runs)")]


def upsert_run(metrics: dict, json_path, objects_path=None, replay_path=None,
               map_path=None, outdir=None, conn=None, joins=None) -> None:
    """Insert or replace one run (and its beatmap) in the index.

    Best-effort by design: ``analyze`` calls this after writing its JSON, and a
    read-only or locked index must not lose the analysis. Errors are printed
    and swallowed by :func:`index_run`; this function itself raises.
    """
    outdir = Path(outdir or Path(json_path).parent)
    json_path = Path(json_path)
    own = conn is None
    conn = conn or connect(outdir / DB_FILENAME)
    try:
        if objects_path is None:
            candidate = json_path.with_name(
                json_path.name[:-len("_metrics.json")] + "_objects.json") \
                if json_path.name.endswith("_metrics.json") else None
            objects_path = candidate if candidate and candidate.is_file() else None
        st = json_path.stat()
        row = metrics_to_row(metrics, json_path, objects_path, replay_path,
                             map_path, mtime=st.st_mtime, size=st.st_size)
        beatmap_id = (_upsert_beatmap(conn, row["beatmap_md5"], map_path=map_path)
                      if row["beatmap_md5"] else None)
        joins = joins if joins is not None else load_joins(outdir)
        row.update(_join_values(row, joins, beatmap_id))
        cols = _run_columns(conn)
        values = [row.get(c) for c in cols]
        conn.execute(
            f"INSERT OR REPLACE INTO runs ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})", values)
        conn.commit()
    finally:
        if own:
            conn.close()


def index_run(metrics: dict, json_path, **kwargs) -> bool:
    """Upsert a run without ever raising: ``analyze`` must not fail on this."""
    if os.environ.get("OSU_NO_INDEX"):
        return False
    try:
        upsert_run(metrics, json_path, **kwargs)
        return True
    except Exception as exc:
        print(f"  ! index: could not record {os.path.basename(os.fspath(json_path))}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return False


# --------------------------------------------------------------- the sweep --

def _metrics_files(root: Path) -> list[Path]:
    return sorted(root.glob("*_metrics.json"))


def sweep(outdir=None, rebuild: bool = False, quiet: bool = False,
          check: bool = False) -> dict:
    """Bring the index in line with ``out/``; returns a stats dict.

    ``check=True`` computes the same diff and writes nothing.
    """
    root = Path(os.path.abspath(Path(outdir or _default_outdir())))
    path = root / DB_FILENAME
    started = time.time()
    files = _metrics_files(root)
    if rebuild and path.exists():
        # a schema from another build cannot be opened at all, so rebuilding
        # has to start from the file, not from the connection
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(path) + suffix).unlink()
            except FileNotFoundError:
                pass
    conn = connect(path)
    try:
        if rebuild and not check:
            conn.executescript("DELETE FROM runs; DELETE FROM beatmaps; "
                               "DELETE FROM annotations;")
            conn.commit()
        known = {r["json_path"]: r for r in conn.execute(
            "SELECT json_path, run_id, mtime, size FROM runs")}

        stats = {"runs": 0, "added": 0, "updated": 0, "unchanged": 0,
                 "removed": 0, "failed": 0, "beatmaps": 0, "seconds": 0.0}
        new_paths = set()
        resolver = _MapResolver(conn)
        joins = load_joins(root)

        for i, fp in enumerate(files, 1):
            fp_str = os.fspath(fp)
            new_paths.add(fp_str)
            try:
                st = fp.stat()
            except OSError:
                continue
            prev = known.get(fp_str)
            if prev is not None and prev["mtime"] == st.st_mtime \
                    and prev["size"] == st.st_size:
                stats["unchanged"] += 1
                if check:
                    continue
                # join columns can change without the artifact changing
                row = conn.execute("SELECT * FROM runs WHERE json_path = ?",
                                   (fp_str,)).fetchone()
                if row is not None:
                    bm = conn.execute("SELECT beatmap_id FROM beatmaps WHERE beatmap_md5 = ?",
                                      (row["beatmap_md5"],)).fetchone()
                    values = _join_values(dict(row), joins,
                                          bm["beatmap_id"] if bm else None)
                    conn.execute("UPDATE runs SET sr = ?, pp = ?, rank_status = ? "
                                 "WHERE run_id = ?",
                                 (values["sr"], values["pp"], values["rank_status"],
                                  row["run_id"]))
                continue
            if check:
                stats["added" if prev is None else "updated"] += 1
                continue
            try:
                with open(fp) as fh:
                    metrics = json.load(fh)
            except (OSError, ValueError) as exc:
                stats["failed"] += 1
                print(f"  ! unreadable metrics {fp.name}: {exc}", file=sys.stderr)
                continue
            objects = fp.with_name(fp.name[:-len("_metrics.json")] + "_objects.json")
            try:
                _upsert_with(conn, metrics, fp, objects if objects.is_file() else None,
                             resolver, joins, stats, prev)
            except Exception as exc:
                stats["failed"] += 1
                print(f"  ! {fp.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            stats["runs"] += 1
            if not quiet and i % 250 == 0:
                print(f"  indexed {i}/{len(files)}...", file=sys.stderr)

        # rows whose artifact vanished
        for fp_str, row in known.items():
            if fp_str in new_paths or os.path.isfile(fp_str):
                continue
            stats["removed"] += 1
            if not check:
                conn.execute("DELETE FROM runs WHERE json_path = ?", (fp_str,))
        if not check:
            sync_annotations(conn, root)
            sync_critiques(conn, root)
            conn.commit()
        stats["beatmaps"] = conn.execute("SELECT COUNT(*) FROM beatmaps").fetchone()[0]
        stats["runs"] = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        stats["seconds"] = round(time.time() - started, 1)
        return stats
    finally:
        conn.close()


def _upsert_with(conn, metrics, fp, objects_path, resolver, joins, stats, prev):
    if prev is None:
        stats["added"] += 1
    else:
        stats["updated"] += 1
    st = fp.stat()
    row = metrics_to_row(metrics, fp, objects_path, mtime=st.st_mtime, size=st.st_size)
    # a sweep has no replay path; keep one an earlier analyze recorded
    if prev is not None:
        old = conn.execute("SELECT replay_path, map_path FROM runs WHERE json_path = ?",
                           (os.fspath(fp),)).fetchone()
        if old is not None:
            row["replay_path"] = row["replay_path"] or old["replay_path"]
            row["map_path"] = row["map_path"] or old["map_path"]
    beatmap_id = (_upsert_beatmap(conn, row["beatmap_md5"],
                                  map_path=row["map_path"], resolver=resolver)
                  if row["beatmap_md5"] else None)
    row.update(_join_values(row, joins, beatmap_id))
    cols = _run_columns(conn)
    conn.execute(
        f"INSERT OR REPLACE INTO runs ({', '.join(cols)}) "
        f"VALUES ({', '.join('?' * len(cols))})",
        [row.get(c) for c in cols])


def sync_annotations(conn: sqlite3.Connection, outdir) -> int:
    """Replace the annotations mirror from the canonical sidecar files.

    Annotations are authored data: the DB is a copy, the files are the truth.
    Cheap enough (one file per annotated map) to redo on every sweep.
    """
    from . import annotations

    notes = annotations.all_notes(outdir)
    conn.execute("DELETE FROM annotations")
    for note in notes:
        conn.execute(
            "INSERT OR REPLACE INTO annotations (note_id, scope, beatmap_md5, "
            "replay_md5, t_map, body, tags, created_at, updated_at, source_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (note["note_id"], note["scope"], note["beatmap_md5"],
             note.get("replay_md5"), note.get("t_map"), note["body"],
             ",".join(note.get("tags") or []), note["created_at"],
             note.get("updated_at"),
             os.fspath(annotations.sidecar_path(outdir, note["beatmap_md5"]))))
    return len(notes)


def sync_critiques(conn: sqlite3.Connection, outdir) -> int:
    """Replace the critiques mirror from ``out/critiques/*.json`` (canonical)."""
    from . import critiques

    rows = critiques.all_critiques(outdir)
    conn.execute("DELETE FROM critiques")
    for doc in rows:
        conn.execute(
            "INSERT OR REPLACE INTO critiques (run_id, replay_md5, beatmap_md5, "
            "model, prompt_hash, run_hash, created, body, source_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc["run_id"], doc.get("replay_md5"), doc.get("beatmap_md5"),
             doc.get("model"), doc.get("prompt_hash"), doc.get("run_hash"),
             doc.get("created"), doc["body"],
             os.fspath(critiques.path_for(outdir, doc["run_id"]))))
    return len(rows)


def check(outdir=None) -> dict:
    """Report drift between the artifacts and the index without writing."""
    root = Path(os.path.abspath(Path(outdir or _default_outdir())))
    path = root / DB_FILENAME
    if not path.exists():
        files = _metrics_files(root)
        return {"index": os.fspath(path), "ok": False, "new": [f.name for f in files],
                "updated": [], "missing": [], "note": "index does not exist"}
    conn = connect(path)
    try:
        known = {r["json_path"]: r for r in conn.execute(
            "SELECT json_path, run_id, mtime, size FROM runs")}
    finally:
        conn.close()
    new, updated, missing = [], [], []
    seen = set()
    for fp in _metrics_files(root):
        fp_str = os.fspath(fp)
        seen.add(fp_str)
        prev = known.get(fp_str)
        if prev is None:
            new.append(fp.name)
            continue
        st = fp.stat()
        if prev["mtime"] != st.st_mtime or prev["size"] != st.st_size:
            updated.append(fp.name)
    for fp_str in known:
        if fp_str not in seen:
            missing.append(os.path.basename(fp_str))
    return {"index": os.fspath(path), "ok": not (new or updated or missing),
            "new": new, "updated": updated, "missing": missing}


# ------------------------------------------------------------------ queries --

def open_readonly(outdir=None) -> sqlite3.Connection | None:
    """The server's read handle: None when there is no index yet."""
    path = db_path(outdir)
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_run(conn, run_id: str):
    """The newest artifact for a run id (re-exports share one id)."""
    return conn.execute(
        "SELECT * FROM runs WHERE run_id = ? ORDER BY mtime DESC, json_path LIMIT 1",
        (run_id,)).fetchone()


def runs_for_map(conn, beatmap_md5: str, order: str = "played_at",
                 dedupe: bool = True) -> list:
    """Every attempt at a map, newest first by the requested column.

    ``dedupe`` keeps the newest artifact per run id: re-exporting a play must
    not make it look like you played the map twice.
    """
    if order not in ("played_at", "accuracy", "ur"):
        order = "played_at"
    rows = conn.execute(
        f"SELECT * FROM runs WHERE beatmap_md5 = ? "
        f"ORDER BY {order} DESC, mtime DESC", (beatmap_md5,)).fetchall()
    if not dedupe:
        return rows
    seen, out = set(), []
    for row in rows:
        if row["run_id"] in seen:
            continue
        seen.add(row["run_id"])
        out.append(row)
    return out


def get_beatmap(conn, beatmap_md5: str):
    return conn.execute("SELECT * FROM beatmaps WHERE beatmap_md5 = ?",
                        (beatmap_md5,)).fetchone()
