"""Tests for ``library_beatmaps``: the map-side features recommendations need.

The fixtures are six deliberately-shaped maps (jumps, stream, anti-flow,
slider-heavy, mania, too-short) with no replays at all, so every number here is
a property of the map and nothing has to be anonymised.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from osu_critique import index, library

FIXTURES = Path(__file__).parent / "fixtures" / "library"


def fixture(name):
    return FIXTURES / f"{name}.osu"


# ------------------------------------------------------------- extraction --

def test_jump_map_is_jump_spaced():
    f = library.extract(fixture("lib_jumps"))
    assert f["mode"] == 0
    assert f["n_objects"] == 160
    assert f["jump_share"] == pytest.approx(1.0)
    assert f["bigjump_share"] == 0.0
    assert f["anti_flow_share"] == 0.0
    assert f["bpm"] == pytest.approx(180.0)
    assert f["length_ms"] == pytest.approx(26500.0, abs=1.0)


def test_stream_map_has_sustained_material():
    f = library.extract(fixture("lib_stream"))
    assert f["stream_share"] == pytest.approx(1.0)
    assert f["sustained_share"] > 0.9
    assert f["sustained_max"] >= 100
    assert f["sustained_nps"] == pytest.approx(12.0, abs=0.5)


def test_antiflow_map_turns_back_on_itself():
    f = library.extract(fixture("lib_antiflow"))
    assert f["anti_flow_share"] == pytest.approx(1.0)
    assert f["flow_share"] == 0.0


def test_slider_map_reports_its_slider_ratio():
    f = library.extract(fixture("lib_sliders"))
    assert f["n_sliders"] == 90
    assert f["slider_ratio"] == pytest.approx(0.75)
    # 1/1 gaps are slower than the sustained detector's 250 ms ceiling
    assert f["sustained_share"] == 0.0


def test_mania_map_keeps_its_mode_and_is_not_std():
    f = library.extract(fixture("lib_mania"))
    assert f["mode"] == 3
    assert f["mode"] != 0


def test_short_map_is_short():
    f = library.extract(fixture("lib_short"))
    assert f["length_ms"] < 5000
    assert f["n_objects"] == 12


def test_extract_md5_is_the_file_md5():
    import hashlib
    f = library.extract(fixture("lib_jumps"))
    assert f["beatmap_md5"] == hashlib.md5(fixture("lib_jumps").read_bytes()).hexdigest()


@pytest.mark.parametrize("field", ["ar", "od", "cs", "hp", "density",
                                   "strain_aim_max", "strain_speed_max"])
def test_scalar_fields_are_present(field):
    f = library.extract(fixture("lib_jumps"))
    assert f[field] is not None


def test_sr_is_computed_when_rosu_is_installed():
    pytest.importorskip("rosu_pp_py")
    f = library.extract(fixture("lib_jumps"))
    assert f["sr"] is not None and f["sr"] > 0


def test_sr_can_be_skipped_without_the_stars_extra():
    f = library.extract(fixture("lib_jumps"), want_sr=False)
    assert f["sr"] is None


# ------------------------------------------------------------------- scan --

def test_scan_indexes_fixture_maps(tmp_path):
    stats = library.scan(tmp_path, extra_sources=[str(FIXTURES)], quiet=True)
    assert stats["maps"] == 6
    assert stats["added"] == 6
    assert stats["failed"] == 0
    conn = index.connect(index.db_path(tmp_path))
    try:
        titles = {r["title"] for r in conn.execute(
            "SELECT title FROM library_beatmaps")}
        assert titles == {"lib_jumps", "lib_stream", "lib_antiflow",
                          "lib_sliders", "lib_mania", "lib_short"}
        summary = library.summary(conn)
        assert summary["maps"] == 6
        assert summary["scanned_at"]
    finally:
        conn.close()


def test_scan_is_incremental(tmp_path):
    library.scan(tmp_path, extra_sources=[str(FIXTURES)], quiet=True)
    again = library.scan(tmp_path, extra_sources=[str(FIXTURES)], quiet=True)
    assert again["unchanged"] == 6
    assert again["added"] == 0 and again["updated"] == 0


def test_scan_reparses_a_touched_file(tmp_path):
    import os
    src = fixture("lib_jumps")
    work = tmp_path / "maps"
    work.mkdir()
    target = work / src.name
    target.write_bytes(src.read_bytes())
    library.scan(tmp_path, extra_sources=[str(work)], quiet=True)
    st = target.stat()
    os.utime(target, (st.st_atime, st.st_mtime + 10))
    again = library.scan(tmp_path, extra_sources=[str(work)], quiet=True)
    assert again["updated"] == 1
    assert again["unchanged"] == 0


def test_scan_drops_a_deleted_map(tmp_path):
    work = tmp_path / "maps"
    work.mkdir()
    (work / "lib_jumps.osu").write_bytes(fixture("lib_jumps").read_bytes())
    library.scan(tmp_path, extra_sources=[str(work)], quiet=True)
    (work / "lib_jumps.osu").unlink()
    again = library.scan(tmp_path, extra_sources=[str(work)], quiet=True)
    assert again["removed"] == 1
    assert again["maps"] == 0


def test_rebuild_reparses_everything(tmp_path):
    library.scan(tmp_path, extra_sources=[str(FIXTURES)], quiet=True)
    stats = library.scan(tmp_path, extra_sources=[str(FIXTURES)], rebuild=True,
                         quiet=True)
    assert stats["maps"] == 6
    assert stats["added"] == 6
    assert stats["unchanged"] == 0


def test_rows_are_the_std_candidates(tmp_path):
    library.scan(tmp_path, extra_sources=[str(FIXTURES)], quiet=True)
    conn = index.connect(index.db_path(tmp_path))
    try:
        titles = sorted(r["title"] for r in library.rows(conn))
        assert "lib_mania" not in titles          # mode != 0
        assert len(titles) == 5
        row = conn.execute(
            "SELECT * FROM library_beatmaps WHERE title = 'lib_stream'").fetchone()
        feats = library.features(row)
        assert feats["stream_share"] == pytest.approx(1.0)
        assert json.loads(row["features_json"])["n_objects"] == 160
    finally:
        conn.close()


def test_summary_is_none_before_the_first_scan(tmp_path):
    (tmp_path / "out").mkdir()
    conn = index.connect(index.db_path(tmp_path / "out"))
    try:
        assert library.summary(conn) is None
    finally:
        conn.close()


# ------------------------------------------------------------------- cli ---

def test_cli_scan_writes_the_table(tmp_path, capsys):
    from osu_critique import cli

    rc = cli.main(["library", "scan", "--outdir", str(tmp_path),
                   "--source", str(FIXTURES), "--quiet"])
    assert rc == 0
    assert "library: 6 maps" in capsys.readouterr().out
    conn = index.connect(index.db_path(tmp_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM library_beatmaps").fetchone()[0] == 6
    finally:
        conn.close()


def test_geometry_block_names_what_a_known_map_contains():
    # geo_stream is generated with triangles/squares/circles at 1/4 gaps
    f = library.extract(Path(__file__).parent / "fixtures" / "patterns" / "geo_stream.osu",
                        want_sr=False)
    g = f["geometry"]
    assert 0.1 < g["coverage"] <= 1.0
    assert g["shapes"]["triangle"]["segments"] >= 1
    assert any(lbl.endswith("triangle stream") for lbl in g["labels"])
    assert library.FEATURE_VERSION == 3


def test_geometry_block_is_deterministic():
    p = Path(__file__).parent / "fixtures" / "patterns" / "geo_clean.osu"
    a = library.extract(p, want_sr=False)["geometry"]
    assert a == library.extract(p, want_sr=False)["geometry"]
