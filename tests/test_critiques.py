"""Stored critiques: hashes, staleness, sidecars, and the index mirror."""
from __future__ import annotations

import json

import pytest

from osu_critique import critiques

RUN = "a" * 32
MD5 = "b" * 32


def metrics(accuracy=0.9):
    return {"beatmap_md5": MD5, "replay_md5": RUN, "accuracy": accuracy,
            "ur": 120.0, "tag": "one"}


def note(body="hard part", t=12.0):
    return {"note_id": "n1", "scope": "map", "body": body, "t_map": t,
            "tags": [], "created_at": "2026-10-24T00:00:00+00:00"}


def test_save_load_remove_roundtrip(tmp_path):
    doc = critiques.build(metrics(), [note()], "system", "m1", "it was timing",
                          run_id=RUN)
    path = critiques.save(tmp_path, doc)
    assert path.is_file() and path.name == f"{RUN}.json"
    loaded = critiques.load(tmp_path, RUN)
    assert loaded["body"] == "it was timing"
    assert loaded["model"] == "m1"
    assert loaded["beatmap_md5"] == MD5
    assert critiques.remove(tmp_path, RUN) is True
    assert critiques.remove(tmp_path, RUN) is False
    assert critiques.load(tmp_path, RUN) is None


def test_run_hash_is_stable_and_reacts_to_metrics_and_notes():
    a = critiques.run_hash(metrics(), [note()])
    b = critiques.run_hash(metrics(), [note()])
    assert a == b
    assert critiques.run_hash(metrics(0.8), [note()]) != a
    assert critiques.run_hash(metrics(), [note("different")]) != a
    assert critiques.run_hash(metrics(), []) != a


def test_staleness_rules():
    m, n, system = metrics(), [note()], "framework"
    stored = critiques.build(m, n, system, "m1", "body", run_id=RUN)
    assert critiques.is_stale(None, m, n, system) is False
    assert critiques.is_stale(stored, m, n, system) is False
    assert critiques.is_stale(stored, metrics(0.5), n, system) is True
    assert critiques.is_stale(stored, m, [note("new")], system) is True
    assert critiques.is_stale(stored, m, n, "a new framework") is True
    # a different model is a different opinion, not a stale critique
    other = dict(stored, model="m2")
    assert critiques.is_stale(other, m, n, system) is False


def test_filenames_are_portable_and_the_run_id_survives(tmp_path):
    path = critiques.save(tmp_path, {
        "run_id": "tag:foolmoon", "body": "x", "model": "m",
        "prompt_hash": "p", "run_hash": "r"})
    assert path.name == "tag_foolmoon.json"
    assert critiques.load(tmp_path, "tag:foolmoon")["run_id"] == "tag:foolmoon"


def test_corrupt_or_empty_sidecars_are_ignored(tmp_path):
    directory = critiques.critiques_dir(tmp_path)
    directory.mkdir(parents=True)
    (directory / "broken.json").write_text("{not json")
    (directory / "empty.json").write_text(json.dumps({"run_id": "r", "body": ""}))
    assert critiques.all_critiques(tmp_path) == []


def test_index_mirrors_critiques_and_survives_a_db_delete(tmp_path):
    from osu_critique import index

    critiques.save(tmp_path, critiques.build(metrics(), [], "sys", "m1",
                                             "stored", run_id=RUN))
    index.sweep(tmp_path)
    (tmp_path / index.DB_FILENAME).unlink()
    index.sweep(tmp_path)
    conn = index.connect(tmp_path / index.DB_FILENAME)
    try:
        row = conn.execute("SELECT * FROM critiques").fetchone()
        assert row["run_id"] == RUN
        assert row["body"] == "stored"
        assert row["model"] == "m1"
    finally:
        conn.close()
    # the canonical file was never touched by any of that
    assert critiques.load(tmp_path, RUN)["body"] == "stored"


# ------------------------------------------------------------ scope files ---

def test_scope_sidecars_are_canonical_and_keep_their_text(tmp_path):
    from osu_critique import critiques

    doc = critiques.build_scope(
        digest="d" * 64, text="# Critique selection\n\nhello", selection={"maps": ["a"]},
        system="SYS", model="m", body="the answer", n_runs=3, n_maps=2,
        first="2026-10-01T10:00:00", last="2026-10-02T10:00:00")
    path = critiques.save_scope(tmp_path, doc)
    assert path.parts[-2:] == ("scope", "d" * 64 + ".json")
    loaded = critiques.load_scope(tmp_path, "d" * 64)
    assert loaded["text"] == "# Critique selection\n\nhello"
    assert loaded["body"] == "the answer"
    assert loaded["selection"] == {"maps": ["a"]}
    assert loaded["prompt_hash"] == critiques.prompt_hash("SYS")


def test_scope_listing_is_newest_first_and_skips_other_files(tmp_path):
    from osu_critique import critiques

    for digest, created in (("a" * 64, "2026-10-01T10:00:00"),
                            ("b" * 64, "2026-10-02T10:00:00")):
        doc = critiques.build_scope(
            digest=digest, text="t", selection={}, system="S", model="m",
            body="b", n_runs=1, n_maps=1, first=None, last=None)
        doc["created"] = created
        critiques.save_scope(tmp_path, doc)
    (critiques.scope_dir(tmp_path) / "junk.json").write_text("{not json")
    rows = critiques.all_scopes(tmp_path)
    assert [r["hash"] for r in rows] == ["b" * 64, "a" * 64]


def test_removing_a_scope_leaves_the_per_run_ones_alone(tmp_path):
    from osu_critique import critiques

    critiques.save_scope(tmp_path, critiques.build_scope(
        digest="c" * 64, text="t", selection={}, system="S", model="m",
        body="b", n_runs=1, n_maps=1, first=None, last=None))
    assert critiques.remove_scope(tmp_path, "c" * 64) is True
    assert critiques.load_scope(tmp_path, "c" * 64) is None
    assert critiques.remove_scope(tmp_path, "c" * 64) is False
