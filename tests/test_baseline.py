"""Rolling baselines: comparing a run against the player's own stored history.

The point of the normalisation is that maps of different shapes are comparable:
timing spread is in % of the 300-window (OD- and mod-normalised), miss rate per
100 objects (length-normalised) and aim pooled over one required-speed band
(demand-normalised). A percentile over too few runs is not a baseline, so the
block says so instead of guessing.
"""
import copy
import json
from pathlib import Path

import pytest

from osu_critique.metrics import baseline as B
from osu_critique.cli import main

SAMPLE = json.loads((Path(__file__).parent.parent / "examples"
                     / "sample_metrics.json").read_text())


def run(tag, *, ur_pct=50.0, miss=0, n=200, aim_band=0.40, md5="m" * 32,
        played="2026-09-01T10:00:00", ceiling=None, ur=None, windows=None):
    """A realistic metrics dict (the shipped sample) with the fields tuned."""
    m = copy.deepcopy(SAMPLE)
    m.update({
        "tag": tag, "beatmap_md5": md5, "played_at": played,
        "replay_md5": tag + "-replay", "n_objects": n,
        "ur_pct_of_300_window": ur_pct,
        "counts_detected": {"300": n - miss, "100": 0, "50": 0, "miss": miss},
        "aim_mode": {"ceiling": ceiling if ceiling is not None else [
            {"v_lo": 0.5, "v_hi": 1.0, "n": n // 3, "mean_r": aim_band},
            {"v_lo": 1.0, "v_hi": 1.5, "n": n // 3, "mean_r": aim_band},
        ]},
    })
    if ur is not None:
        m["ur"] = ur
    if windows is not None:
        m["windows_ms"] = windows
    return m


# --------------------------------------------------------- normalisation ----

def test_timing_spread_is_ur_as_a_share_of_the_window():
    m = run("a", ur_pct=42.5)
    assert B.normalise(m)["timing_spread"] == pytest.approx(42.5)
    # falls back to ur / window when the ratio was not stored
    m2 = run("b", ur_pct=None, ur=184.0, windows={"300": 32.0})
    m2.pop("ur_pct_of_300_window")
    assert B._timing_spread(m2) == pytest.approx(184.0 / 10 / 32.0 * 100, rel=1e-6)


def test_miss_rate_is_per_hundred_objects():
    assert B._miss_rate(run("a", miss=5, n=200)) == pytest.approx(2.5)
    assert B._miss_rate({"counts_detected": {}, "n_objects": 0}) is None


def test_aim_is_pooled_over_the_demand_band_only():
    m = run("a", ceiling=[
        {"v_lo": 0.0, "v_hi": 0.5, "n": 100, "mean_r": 9.9},    # outside the band
        {"v_lo": 0.5, "v_hi": 1.0, "n": 10, "mean_r": 0.30},
        {"v_lo": 1.0, "v_hi": 1.5, "n": 10, "mean_r": 0.50},
        {"v_lo": 3.0, "v_hi": 99.0, "n": 100, "mean_r": 9.9},   # outside the band
    ])
    assert B._aim_at_demand(m) == pytest.approx(0.40)
    assert B._aim_at_demand({"aim_mode": {"ceiling": []}}) is None


def test_better_than_counts_the_runs_this_one_beats():
    values = [10.0, 20.0, 30.0, 40.0]
    assert B.better_than_pct(25.0, values) == pytest.approx(50.0)   # beats 30, 40
    assert B.better_than_pct(5.0, values) == pytest.approx(100.0)
    assert B.better_than_pct(None, values) is None


# ------------------------------------------------------------- history -----

def test_history_excludes_the_run_itself_and_needs_enough_runs():
    me = run("me", ur_pct=20.0)
    others = [run(f"o{i}", ur_pct=50.0 + i) for i in range(9)]
    block = B.history_report(me, [("me", me)] + [(f"o{i}", m) for i, m in enumerate(others)])
    assert block["n_runs"] == 9
    ts = block["metrics"]["timing_spread"]
    assert ts["enough"] is True and ts["n"] == 9
    assert ts["better_than_pct"] == pytest.approx(100.0)
    assert "better than" in block["verdict"]

    thin = B.history_report(me, [("me", me), ("x", run("x"))])
    assert thin["metrics"]["timing_spread"]["enough"] is False
    assert "not enough stored runs" in thin["verdict"]


def test_describe_renders_every_metric():
    me = run("me", ur_pct=20.0, miss=0, aim_band=0.30)
    rows = [("me", me)] + [(f"o{i}", run(f"o{i}", ur_pct=60.0, miss=8, aim_band=0.5))
                           for i in range(9)]
    lines = B.describe(B.history_report(me, rows))
    assert lines[0].startswith("AGAINST YOUR HISTORY (9 stored runs")
    body = "\n".join(lines)
    assert "timing spread" in body and "miss rate" in body
    assert "0.5-2.0 px/ms demand" in body
    assert "verdict:" in body


def test_the_same_run_is_identified_by_replay_hash_not_tag():
    me = run("renamed", md5="m" * 32)
    same = run("original", md5="m" * 32)
    same["replay_md5"] = me["replay_md5"]
    block = B.history_report(me, [("original", same)])
    assert block["n_runs"] == 0          # the only stored run *is* this one


# ----------------------------------------------------------------- cli -----

def _write(dirpath, tag, **kw):
    m = run(tag, **kw)
    (dirpath / f"{tag}_metrics.json").write_text(json.dumps(m))
    return m


def test_cli_report_adds_the_history_section(tmp_path, capsys):
    for i in range(9):
        _write(tmp_path, f"old{i}", ur_pct=60.0 + i)
    me = _write(tmp_path, "mine", ur_pct=20.0)
    assert main(["report", str(tmp_path / "mine_metrics.json"),
                 "--history", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "AGAINST YOUR HISTORY (9 stored runs" in out
    assert "better than" in out
    # and it can be turned off
    assert main(["report", str(tmp_path / "mine_metrics.json"),
                 "--history", str(tmp_path), "--no-history"]) == 0
    assert "AGAINST YOUR HISTORY" not in capsys.readouterr().out
    assert me["tag"] == "mine"


# ------------------------------------------------------- compatibility -----

def test_the_shipped_sample_still_renders():
    """``examples/sample_metrics.json`` predates several blocks; it must still render."""
    from osu_critique.cli import render_report
    from osu_critique.report import console_summary
    text = render_report(copy.deepcopy(SAMPLE))
    assert "# Report" in text
    console_summary(copy.deepcopy(SAMPLE))


def test_a_pre_0_9_metrics_file_still_renders():
    """Metrics written before the stream rewrite have no material fields."""
    from osu_critique.cli import render_report
    from osu_critique.report import console_summary
    legacy = copy.deepcopy(SAMPLE)          # a real metrics dump from 0.8.0
    for gone in ("aim_mode", "autopsy", "time_base"):
        legacy.pop(gone, None)
    legacy["streams"] = {"n_segments": 1, "segments": [
        {"t_start": 1000.0, "t_end": 1400.0, "n": 5, "miss": 1,
         "mean_err": 3.0, "std_err": 12.0, "alt_ratio": 0.9,
         "key_pattern": "ABABA"}]}          # no gap_ms / notes_per_s / kinds
    text = render_report(legacy)
    assert "## Streams" in text and "5 notes" in text
    console_summary(legacy)
