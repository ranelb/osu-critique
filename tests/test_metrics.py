"""Metric derivations: aim error against cursor speed, UR against the hit window."""
import numpy as np
import pytest

from osu_critique.report import aim_velocity, analyze

MAP = "tests/fixtures/aaaaa.osu"
REPLAY = "tests/fixtures/aaaaa.osr"


def test_aim_velocity_recovers_a_known_slope():
    rng = np.random.default_rng(0)
    v = rng.uniform(0.5, 3.0, 200)
    a = 0.2 + 0.15 * v                      # exactly linear in cursor speed
    out = aim_velocity(list(zip(v, a)))
    assert out["n"] == 200
    assert abs(out["slope_r_per_px_ms"] - 0.15) < 1e-9
    assert out["r2"] > 0.999
    assert len(out["bins"]) == 4
    assert out["bins"][0]["mean_aim_r"] < out["bins"][-1]["mean_aim_r"]


def test_aim_velocity_flat_ceiling_is_a_flat_slope():
    v = np.linspace(0.5, 3.0, 100)
    out = aim_velocity([(x, 0.35) for x in v])
    assert abs(out["slope_r_per_px_ms"]) < 1e-9


def test_aim_velocity_needs_enough_points():
    out = aim_velocity([(1.0, 0.4), (2.0, 0.5)])
    assert out["slope_r_per_px_ms"] is None
    assert out["bins"] == []


def test_metrics_carry_velocity_and_window_normalised_ur(tmp_path):
    if not (np and REPLAY):
        pytest.skip("fixtures missing")
    m = analyze(REPLAY, MAP, tag="aaaaa", outdir=str(tmp_path), console=False)
    avs = m["aim_vs_speed"]
    assert avs["n"] > 0
    assert avs["slope_r_per_px_ms"] is not None
    # 65 objects: the quartile bins must partition the measured objects
    assert sum(b["n"] for b in avs["bins"]) >= avs["n"] - 4
    ur_pct = m["ur_pct_of_300_window"]
    assert ur_pct is not None and ur_pct >= 0
    w300 = (80 - 6 * m["difficulty"]["OD"])
    assert ur_pct == pytest.approx(m["ur"] / 10.0 / w300 * 100.0, rel=1e-6)


def test_aim_velocity_ignores_export_artefacts():
    """Dropped-frame speed spikes and non-finite pairs are not a flick."""
    pairs = [(1.0 + 0.01 * i, 0.3) for i in range(20)]
    pairs += [(1e6, 0.9), (float("inf"), 0.9), (float("nan"), 0.9), (None, 0.9)]
    out = aim_velocity(pairs)
    assert out["n"] == 20
    assert abs(out["slope_r_per_px_ms"]) < 1e-9


# ------------------------------------------------------------- time base ----

def _analyze(name, tmp_path):
    return analyze(f"tests/fixtures/{name}.osr", f"tests/fixtures/{name}.osu",
                   tag=name, outdir=str(tmp_path), console=False,
                   write_objects=False)


def test_time_base_is_the_identity_when_the_mod_flag_holds(tmp_path):
    m = _analyze("aaaaa", tmp_path)
    tb = m["time_base"]
    assert tb["overridden"] is False
    assert tb["rows_to_player"] == pytest.approx(1.0)
    assert tb["windows_ms_player"] == m["windows_ms"]
    assert tb["note"] is None


def test_time_base_reports_both_clocks_when_calibration_overrides(tmp_path):
    """Domino claims DT but stores frames in map time: 29 ms here is 19 ms felt."""
    m = _analyze("domino", tmp_path)
    tb = m["time_base"]
    assert m["trust"]["scale_overridden"] is True
    assert tb["overridden"] is True
    assert tb["rows_scale"] == pytest.approx(1.0)
    assert tb["rows_to_player"] == pytest.approx(2 / 3, abs=1e-6)
    assert tb["windows_ms_player"]["300"] == pytest.approx(
        m["windows_ms"]["300"] * 2 / 3, rel=1e-9)
    assert tb["windows_ms_player"]["300"] < m["windows_ms"]["300"]
    assert "DT" in tb["note"] and "real play" in tb["note"]


def test_the_player_windows_are_the_windows_of_the_claimed_mod(tmp_path):
    """The invariant that makes the second base meaningful, not decorative."""
    from osu_critique.io.beatmap import load_beatmap, mod_scale, od_windows
    import slider
    m = _analyze("domino", tmp_path)
    r = slider.Replay.from_path("tests/fixtures/domino.osr", retrieve_beatmap=False)
    od = load_beatmap("tests/fixtures/domino.osu").od()
    player = od_windows(od, mod_scale(r))
    for i, k in enumerate(("300", "100", "50")):
        assert m["time_base"]["windows_ms_player"][k] == pytest.approx(player[i], rel=1e-9)


def test_both_readers_label_the_base(tmp_path, capsys):
    from osu_critique.cli import render_report
    from osu_critique.report import console_summary
    m = _analyze("domino", tmp_path)
    console_summary(m)
    out = capsys.readouterr().out
    assert "time base:" in out
    assert "frames' base" in out and "the player felt" in out
    assert "(player time)" in out                  # the profile line is labelled
    text = render_report(m)
    assert "TIME BASE:" in text and "(player time)" in text
    # a play whose flag holds says none of this
    ok = _analyze("aaaaa", tmp_path)
    console_summary(ok)
    assert "time base:" not in capsys.readouterr().out
    assert "TIME BASE" not in render_report(ok)
