"""Cursor-arrival ("aim mode"): the block, its helpers and its figures.

The reference implementation was ``scripts/autopsy.py``; these tests pin the
numbers that used to live only in that script. Two kinds of case:

- hand-built frames, where the cursor's geometry is arithmetic (exact);
- ``tests/fixtures/synth_rx`` (an RX replay with a known cursor path), where the
  whole pipeline must reproduce the designed numbers.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from osu_critique.metrics import aim as A
from osu_critique.report import analyze

FIX = Path(__file__).parent / "fixtures"
MAP = "tests/fixtures/aaaaa.osu"
REPLAY = "tests/fixtures/aaaaa.osr"
RADIUS = 36.48          # CS 4 -> 54.4 - 4.48 * 4


def frames_from(waypoints):
    """``(t, x, y)`` waypoints -> (frames, times) as build_frames returns."""
    frames = [(float(t), float(x), float(y), False, False)
              for t, x, y in waypoints]
    return frames, np.array([f[0] for f in frames])


def obj(i, t, x=100.0, y=100.0, kind="Circle"):
    return {"i": i, "t": float(t), "end": float(t), "x": float(x), "y": float(y),
            "kind": kind}


# ------------------------------------------------------------- helpers ------

def test_cursor_on_the_note_is_zero_distance_with_no_peak_offset():
    objs = [obj(0, 1000)]
    frames, times = frames_from([(0, 0, 0), (1000, 100, 100), (2000, 100, 100)])
    rows = A.cursor_rows(objs, frames, times, RADIUS)
    assert len(rows) == 1
    assert rows[0]["d"] == pytest.approx(0.0, abs=1e-9)
    assert rows[0]["dmin"] == pytest.approx(0.0, abs=1e-9)
    # the sample grid rarely lands on the note instant, so allow one step
    assert abs(rows[0]["peak_off"]) <= A.SAMPLE_MS
    assert rows[0]["entry_off"] is not None and rows[0]["entry_off"] < 0
    blk = A.summarise(rows)
    assert blk["n"] == 1
    assert blk["reached_not_on_time"]["n"] == 0
    assert blk["error_shape"]["short_pct"] is None      # no predecessor -> no axis
    assert blk["by_jump_distance"] == []


def test_a_late_arrival_shows_up_as_a_positive_peak_offset():
    # cursor stays 200 px away until t=1000, then is on the object at t=1100
    objs = [obj(0, 1000)]
    frames, times = frames_from([(0, 300, 100), (1000, 300, 100), (1100, 100, 100),
                                 (2100, 100, 100)])
    blk = A.summarise(A.cursor_rows(objs, frames, times, RADIUS))
    d = blk["distance_at_note_r"]
    assert d["mean"] == pytest.approx(200 / RADIUS, rel=1e-6)   # still far away
    assert blk["peak_offset_ms"]["median"] == pytest.approx(100.0, abs=1e-6)
    assert blk["closest_approach_r"]["median"] == pytest.approx(0.0, abs=1e-9)
    assert blk["reached_not_on_time"] == {"n": 1, "pct": 100.0}


def test_a_note_the_cursor_never_reaches():
    objs = [obj(0, 1000, x=400)]
    frames, times = frames_from([(0, 100, 100), (3000, 100, 100)])
    blk = A.summarise(A.cursor_rows(objs, frames, times, RADIUS))
    assert blk["closest_approach_r"]["never_inside"] == 1
    assert blk["closest_approach_r"]["inside_pct"] == 0.0
    assert blk["window_entry_ms"]["never_entered"] == 1
    assert blk["window_entry_ms"].get("median") is None
    assert blk["reached_not_on_time"]["n"] == 0


def test_spinners_are_skipped_but_object_indices_are_kept():
    objs = [obj(0, 1000), obj(1, 1500, kind="Spinner"), obj(2, 2000, x=400)]
    frames, times = frames_from([(0, 100, 100), (2000, 100, 100), (4000, 400, 100)])
    rows = A.cursor_rows(objs, frames, times, RADIUS)
    assert [r["i"] for r in rows] == [0, 2]
    assert A.summarise(rows)["n"] == 2


def test_an_empty_play_does_not_crash():
    blk = A.summarise([])
    assert blk["n"] == 0 and blk["ceiling"] == []
    assert blk["distance_at_note_r"] is None


# -------------------------------------------------------- designed fixture --

RX = FIX / "synth_rx.osr"
RX_MAP = FIX / "synth_rx.osu"


@pytest.fixture(scope="module")
def rx_metrics(tmp_path_factory):
    if not RX.exists():
        pytest.skip("synth_rx not generated (run scripts/make_synthetic_fixtures.py)")
    out = tmp_path_factory.mktemp("rx")
    return analyze(str(RX), str(RX_MAP), tag="synth_rx", outdir=str(out),
                   console=False)


def test_rx_fixture_reproduces_the_designed_geometry(rx_metrics):
    """The cursor reaches every object exactly 100 ms late, 60 px short."""
    blk = rx_metrics["aim_mode"]
    assert blk["is_relax"] is True
    assert blk["n"] == 60
    assert blk["window_ms"] == A.WINDOW_MS
    d = blk["distance_at_note_r"]
    assert d["mean"] == pytest.approx(60 / RADIUS, abs=0.01)      # 1.64 r
    assert d["inside_pct"] == 0.0
    assert blk["closest_approach_r"]["median"] == pytest.approx(0.0, abs=1e-9)
    assert blk["closest_approach_r"]["never_inside"] == 0
    assert blk["peak_offset_ms"]["median"] == pytest.approx(100.0, abs=1e-6)
    assert blk["peak_offset_ms"]["late_pct"] == 100.0
    assert blk["window_entry_ms"]["median"] == pytest.approx(40.0, abs=1.0)
    assert blk["reached_not_on_time"] == {"n": 60, "pct": 100.0}
    es = blk["error_shape"]
    assert es["short_pct"] == 100.0 and es["past_pct"] == 0.0
    assert es["along_r"]["median"] == pytest.approx(-60 / RADIUS, abs=0.01)
    assert es["lateral_r"]["median"] == pytest.approx(0.0, abs=1e-6)


def test_rx_fixture_ceiling_and_time_bins(rx_metrics):
    blk = rx_metrics["aim_mode"]
    # 300 px in 500 ms -> a single 0.5-1.0 px/ms demand bin over the 59 gaps
    assert len(blk["ceiling"]) == 1
    ce = blk["ceiling"][0]
    assert (ce["v_lo"], ce["v_hi"], ce["n"]) == (0.5, 1.0, 59)
    assert ce["mean_r"] == pytest.approx(60 / RADIUS, abs=0.01)
    assert ce["peak_ms"] == pytest.approx(100.0, abs=1e-6)
    assert len(blk["by_jump_distance"]) == 1
    assert blk["by_jump_distance"][0]["n"] == 59
    assert len(blk["over_time"]) == 6            # 30 s play, 6 bins of 10 notes
    assert sum(b["n"] for b in blk["over_time"]) == 59


def test_rx_metrics_are_json_safe_and_in_the_report(rx_metrics):
    json.dumps(rx_metrics["aim_mode"], allow_nan=False)
    assert "aim_mode" in rx_metrics
    assert rx_metrics["trust"]["trustworthy"] is True
    from osu_critique.cli import render_report
    text = render_report(rx_metrics)
    assert "cursor arrival" in text
    assert "there but not then" in text
    assert "aim ceiling" in text


def test_rx_aim_describe_and_console(rx_metrics, capsys):
    lines = A.describe(rx_metrics["aim_mode"])
    assert lines[0] == "AIM (n=60)"
    assert any("closest approach" in line for line in lines)
    assert any("ceiling curve" in line for line in lines)
    from osu_critique.report import console_summary
    console_summary(rx_metrics)
    out = capsys.readouterr().out
    assert "aim (cursor arrival, n=60)" in out
    assert "ceiling (px/ms" in out


# ------------------------------------------------------------ pipeline ------

def test_aim_block_is_in_every_analysis(tmp_path):
    metrics = analyze(REPLAY, MAP, tag="aaaaa", outdir=str(tmp_path), console=False)
    blk = metrics["aim_mode"]
    assert blk and blk["n"] == metrics["n_objects"]     # aaaaa has no spinners
    assert blk["is_relax"] is False
    if blk["distance_at_note_r"]:
        assert 0 <= blk["distance_at_note_r"]["inside_pct"] <= 100
    json.dumps(blk, allow_nan=False)
    # and it survives the JSON round-trip the consumers use
    on_disk = json.loads((tmp_path / "aaaaa_metrics.json").read_text())
    assert on_disk["aim_mode"]["n"] == blk["n"]


def test_no_aim_flag_skips_the_block(tmp_path):
    metrics = analyze(REPLAY, MAP, tag="noaim", outdir=str(tmp_path),
                      console=False, write_aim=False)
    assert metrics["aim_mode"] is None


def test_aim_figure_is_written(tmp_path):
    pytest.importorskip("matplotlib")
    analyze(REPLAY, MAP, tag="aaaaa", outdir=str(tmp_path), console=False,
            do_charts=True)
    assert (tmp_path / "aaaaa_aim.png").exists()
    assert (tmp_path / "aaaaa_aim.png").stat().st_size > 1000


def test_cli_no_aim_end_to_end(tmp_path):
    from osu_critique.cli import main
    assert main(["analyze", REPLAY, MAP, "cli", "--no-aim",
                 "--outdir", str(tmp_path)]) == 0
    metrics = json.loads((tmp_path / "cli_metrics.json").read_text())
    assert metrics["aim_mode"] is None


# ------------------------------------------------- the acceptance replay ----

RX_ENV = ("OSU_TEST_RX_REPLAY", "OSU_TEST_RX_MAP")


def _rx_reference():
    import os
    r = os.environ.get(RX_ENV[0])
    m = os.environ.get(RX_ENV[1])
    if not (r and m):
        pytest.skip("set OSU_TEST_RX_REPLAY / OSU_TEST_RX_MAP to the author's "
                    "Relax export + map to check the published numbers")
    return r, m


def test_acceptance_on_the_reference_relax_replay(tmp_path):
    """docs/ROADMAP.md item 1 acceptance numbers (within rounding).

    The replay is the author's and is not committed; this runs only where the
    two env vars are set.
    """
    replay, map_path = _rx_reference()
    metrics = analyze(replay, map_path, tag="rx", outdir=str(tmp_path),
                      console=False, write_objects=False)
    blk = metrics["aim_mode"]
    assert blk["n"] > 500
    assert blk["distance_at_note_r"]["mean"] == pytest.approx(0.72, abs=0.03)
    assert blk["closest_approach_r"]["median"] == pytest.approx(0.26, abs=0.03)
    assert blk["peak_offset_ms"]["median"] == pytest.approx(10, abs=5)
    assert blk["reached_not_on_time"]["pct"] == pytest.approx(16.8, abs=2.0)
    ceiling = {b["v_lo"]: b["mean_r"] for b in blk["ceiling"]}
    assert ceiling.get(0.0, 0) == pytest.approx(0.47, abs=0.05)   # <=1 px/ms
    assert blk["ceiling"][-1]["mean_r"] == pytest.approx(1.19, abs=0.08)
