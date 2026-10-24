"""Tests for the derived SQLite index (``out/index.sqlite``).

The index is a projection: nothing here should require an artifact to change
for a join column to move, and a broken index must never lose a run.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from osu_critique import index

FIXTURES = Path(__file__).parent / "fixtures"


def metrics(tag="run", replay="r" * 32, beatmap="m" * 32,
            played_at="2026-10-01T12:00:00", accuracy=0.9, **over):
    doc = {
        "schema_version": 1,
        "tag": tag,
        "beatmap_md5": beatmap,
        "replay_md5": replay,
        "played_at": played_at,
        "player": "player",
        "map": "Artist - Title [Insane]",
        "mods": {"DT": False, "HT": False, "HD": False, "HR": False,
                 "NF": False, "FL": False, "EZ": False, "RX": False, "AP": False},
        "mod_string": "NM",
        "time_scale": 1.0,
        "difficulty": {"CS": 4.0, "AR": 9.0, "OD": 8.0, "HP": 5.0},
        "n_objects": 100,
        "n_objects_map": 100,
        "accuracy": accuracy,
        "max_combo": 99,
        "full_combo": False,
        "ur": 120.0,
        "ur_pct_of_300_window": 50.0,
        "hit_error_ms": {"mean": 1.0, "std": 20.0, "p10": -20.0, "p90": 20.0,
                         "abs_mean": 15.0},
        "whiffed_presses": 1,
        "counts_recorded": {"300": 90, "100": 8, "50": 0, "miss": 2},
        "counts_detected": {"300": 90, "100": 8, "50": 0, "miss": 2},
        "trust": {"trustworthy": True, "abs_delta_total": 0, "judged": 100},
        "failed_play": False,
        "time_base": {"overridden": False},
        "aim_mode": {"is_relax": False},
    }
    doc.update(over)
    return doc


def write_run(outdir: Path, doc: dict, objects: bool = False) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{doc['tag']}_metrics.json"
    path.write_text(json.dumps(doc, indent=1))
    if objects:
        (outdir / f"{doc['tag']}_objects.json").write_text(
            json.dumps({"objects": [{"i": 0}]}))
    return path


@pytest.fixture(autouse=True)
def no_lazer_scan(monkeypatch):
    """The real sweep resolves maps from the lazer store; tests must not."""
    monkeypatch.setattr(index._MapResolver, "_build", lambda self: {})


def open_db(outdir):
    return index.connect(outdir / index.DB_FILENAME)


# ------------------------------------------------------------------- rows ----

def test_upsert_projects_the_listing_fields(tmp_path):
    outdir = tmp_path / "out"
    path = write_run(outdir, metrics(tag="one"))
    index.upsert_run(metrics(tag="one"), path, outdir=outdir)

    conn = open_db(outdir)
    row = index.get_run(conn, "r" * 32)
    assert row["tag"] == "one"
    assert row["beatmap_md5"] == "m" * 32
    assert row["accuracy"] == pytest.approx(0.9)
    assert row["od"] == 8.0
    assert row["trust_ok"] == 1
    assert row["trust_delta"] == 0
    assert row["full_combo"] == 0
    assert row["json_path"] == str(path)
    assert row["objects_missing"] == 1
    assert row["indexed_at"]
    conn.close()


def test_upsert_detects_objects_and_relax(tmp_path):
    outdir = tmp_path / "out"
    doc = metrics(tag="rx", replay="x" * 32,
                  mods={**metrics()["mods"], "AP": True},
                  mod_string="AP")
    path = write_run(outdir, doc, objects=True)
    index.upsert_run(doc, path, outdir=outdir)

    conn = open_db(outdir)
    row = index.get_run(conn, "x" * 32)
    assert row["objects_missing"] == 0
    assert row["objects_path"].endswith("rx_objects.json")
    # autoplay without the RX flag still counts as a relax-like run
    assert row["is_relax"] == 1
    conn.close()


def test_legacy_metrics_keep_the_run_without_a_beatmap(tmp_path):
    outdir = tmp_path / "out"
    legacy = {"tag": "old", "player": "p", "map": "old map", "accuracy": 0.8,
              "ur": 100.0, "hit_error_ms": {"mean": 0, "std": 10},
              "mods": {}, "difficulty": {}, "n_objects": 10,
              "counts_recorded": {}, "counts_detected": {},
              "trust": {}, "aim_mode": {}}
    path = write_run(outdir, legacy)
    index.upsert_run(legacy, path, outdir=outdir)

    conn = open_db(outdir)
    row = index.get_run(conn, "tag:old")
    assert row["replay_md5"] is None
    assert row["beatmap_md5"] == ""
    assert row["schema_version"] is None
    assert conn.execute("SELECT COUNT(*) FROM beatmaps").fetchone()[0] == 0
    conn.close()


def test_beatmap_metadata_is_parsed_and_cached(tmp_path):
    outdir = tmp_path / "out"
    path = write_run(outdir, metrics(tag="one"))
    index.upsert_run(metrics(tag="one"), path, outdir=outdir,
                     map_path=FIXTURES / "deafheaven.osu")

    conn = open_db(outdir)
    bm = index.get_beatmap(conn, "m" * 32)
    assert bm["title"] == "DEAFHEAVEN"
    assert bm["version"] == "EXTREME COLLAB"
    assert bm["background"] == "136969250_p0.jpg"
    assert bm["metadata_missing"] == 0
    assert bm["map_path"] == str(FIXTURES / "deafheaven.osu")
    conn.close()


def test_joins_come_from_the_existing_caches(tmp_path):
    outdir = tmp_path / "out"
    (outdir).mkdir(parents=True)
    (outdir / "stars_by_md5.json").write_text(
        json.dumps({"m" * 32: {"NM": 5.4, "DT": 7.1}}))
    (outdir / "pp_by_replay.json").write_text(
        json.dumps({"r" * 32: {"pp": 123.4}}))
    (outdir / "beatmap_status.json").write_text(
        json.dumps({"42": {"status": "ranked"}}))

    doc = metrics(tag="one")
    map_doc = FIXTURES / "deafheaven.osu"
    path = write_run(outdir, doc)
    index.upsert_run(doc, path, outdir=outdir, map_path=map_doc)

    conn = open_db(outdir)
    row = index.get_run(conn, "r" * 32)
    assert row["sr"] == pytest.approx(5.4)          # NM fallback for mod_string NM
    assert row["pp"] == pytest.approx(123.4)
    bm = index.get_beatmap(conn, "m" * 32)
    if bm["beatmap_id"] == 42:
        assert row["rank_status"] == "ranked"
    conn.close()


def test_malformed_cache_is_not_an_error(tmp_path):
    outdir = tmp_path / "out"
    outdir.mkdir(parents=True)
    (outdir / "stars_by_md5.json").write_text("{not json")
    path = write_run(outdir, metrics(tag="one"))
    index.upsert_run(metrics(tag="one"), path, outdir=outdir)
    conn = open_db(outdir)
    assert index.get_run(conn, "r" * 32)["sr"] is None
    conn.close()


# ------------------------------------------------------------------- sweep ---

def test_sweep_is_incremental_and_removes_vanished_runs(tmp_path):
    outdir = tmp_path / "out"
    write_run(outdir, metrics(tag="a", replay="a" * 32, beatmap="1" * 32))
    write_run(outdir, metrics(tag="b", replay="b" * 32, beatmap="1" * 32))

    first = index.sweep(outdir)
    assert (first["runs"], first["added"], first["failed"]) == (2, 2, 0)

    second = index.sweep(outdir)
    assert second["unchanged"] == 2
    assert second["added"] == 0 and second["updated"] == 0

    # one artifact changes -> updated, and only that one
    write_run(outdir, metrics(tag="a", replay="a" * 32, beatmap="1" * 32,
                              accuracy=0.95))
    third = index.sweep(outdir)
    assert third["updated"] == 1 and third["unchanged"] == 1

    # one vanishes -> removed
    (outdir / "b_metrics.json").unlink()
    fourth = index.sweep(outdir)
    assert fourth["removed"] == 1
    assert fourth["runs"] == 1


def test_sweep_refreshes_joins_without_touching_the_artifact(tmp_path):
    outdir = tmp_path / "out"
    write_run(outdir, metrics(tag="a"))
    index.sweep(outdir)

    (outdir / "stars_by_md5.json").write_text(json.dumps({"m" * 32: {"NM": 6.0}}))
    stats = index.sweep(outdir)
    assert stats["unchanged"] == 1

    conn = open_db(outdir)
    assert index.get_run(conn, "r" * 32)["sr"] == pytest.approx(6.0)
    conn.close()


def test_sweep_survives_an_unreadable_artifact(tmp_path):
    outdir = tmp_path / "out"
    outdir.mkdir(parents=True)
    (outdir / "bad_metrics.json").write_text("{truncated")
    write_run(outdir, metrics(tag="good"))
    stats = index.sweep(outdir)
    assert stats["failed"] == 1
    assert stats["runs"] == 1


def test_sweep_on_an_empty_directory(tmp_path):
    stats = index.sweep(tmp_path / "out")
    assert stats["runs"] == 0 and stats["beatmaps"] == 0
    assert (tmp_path / "out" / index.DB_FILENAME).exists()


def test_rebuild_drops_rows(tmp_path):
    outdir = tmp_path / "out"
    write_run(outdir, metrics(tag="a"))
    index.sweep(outdir)
    stats = index.sweep(outdir, rebuild=True)
    assert stats["added"] == 1
    conn = open_db(outdir)
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    conn.close()


def test_check_reports_drift_without_writing(tmp_path):
    outdir = tmp_path / "out"
    missing = index.check(outdir)
    assert missing["ok"] is False
    assert missing["note"]

    write_run(outdir, metrics(tag="a"))
    index.sweep(outdir)
    assert index.check(outdir)["ok"] is True

    write_run(outdir, metrics(tag="b", replay="b" * 32, beatmap="2" * 32))
    drift = index.check(outdir)
    assert drift["ok"] is False
    assert drift["new"] == ["b_metrics.json"]

    (outdir / "a_metrics.json").unlink()
    drift = index.check(outdir)
    assert "a_metrics.json" in drift["missing"]


# ------------------------------------------------------------------ guards ---

def test_schema_version_mismatch_is_refused(tmp_path):
    outdir = tmp_path / "out"
    outdir.mkdir(parents=True)
    conn = sqlite3.connect(outdir / index.DB_FILENAME)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', '99')")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="rebuild"):
        index.connect(outdir / index.DB_FILENAME)


def test_index_run_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("OSU_NO_INDEX", "1")
    outdir = tmp_path / "out"
    path = write_run(outdir, metrics(tag="a"))
    assert index.index_run(metrics(tag="a"), path, outdir=outdir) is False
    assert not (outdir / index.DB_FILENAME).exists()


def test_index_run_swallows_errors(monkeypatch, tmp_path):
    outdir = tmp_path / "out"
    path = write_run(outdir, metrics(tag="a"))

    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(index, "upsert_run", boom)
    assert index.index_run(metrics(tag="a"), path, outdir=outdir) is False


def test_db_path_accepts_a_directory_or_a_file(tmp_path):
    assert index.db_path(tmp_path) == tmp_path / index.DB_FILENAME
    assert index.db_path(tmp_path / "x.sqlite") == tmp_path / "x.sqlite"


def test_reexported_play_keeps_both_artifacts_but_the_listing_dedupes(tmp_path):
    outdir = tmp_path / "out"
    short = write_run(outdir, metrics(tag="short", replay="d" * 32))
    dated = write_run(outdir, metrics(tag="dated", replay="d" * 32))
    os.utime(short, (1_700_000_000, 1_700_000_000))
    os.utime(dated, (1_700_000_100, 1_700_000_100))

    stats = index.sweep(outdir)
    assert stats["runs"] == 2, "a re-export must not silently delete the other artifact"

    conn = open_db(outdir)
    assert len(index.runs_for_map(conn, "m" * 32, dedupe=False)) == 2
    rows = index.runs_for_map(conn, "m" * 32)
    assert len(rows) == 1
    assert rows[0]["tag"] == "dated", "the newest artifact wins"
    assert index.get_run(conn, "d" * 32)["tag"] == "dated"
    conn.close()


def test_runs_for_map_orders_by_played_at(tmp_path):
    outdir = tmp_path / "out"
    write_run(outdir, metrics(tag="old", replay="1" * 32, beatmap="m" * 32,
                              played_at="2026-09-01T10:00:00"))
    write_run(outdir, metrics(tag="new", replay="2" * 32, beatmap="m" * 32,
                              played_at="2026-10-01T10:00:00"))
    index.sweep(outdir)
    conn = open_db(outdir)
    rows = index.runs_for_map(conn, "m" * 32)
    assert [r["tag"] for r in rows] == ["new", "old"]
    conn.close()


def test_rebuild_recovers_from_another_build(tmp_path):
    out = tmp_path / "out"
    write_run(out, metrics(tag="a"))
    index.sweep(out)
    conn = sqlite3.connect(out / index.DB_FILENAME)
    conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(index.SchemaMismatch):
        index.connect(out / index.DB_FILENAME)
    stats = index.sweep(out, rebuild=True)   # must delete the file, not the rows
    assert stats["runs"] == 1
