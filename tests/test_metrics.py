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
