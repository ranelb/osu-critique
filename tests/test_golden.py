"""Golden regression tests: the pipeline must reproduce the game's recorded
hit counts on known-good replays.

Fixtures live in tests/fixtures/ (committed; they are the author's own
replays — remove the directory if you don't want them public, and the tests
fall back to OSU_TEST_* env vars, then skip).
"""
import os
from pathlib import Path

import pytest

from osu_critique.report import analyze
import slider

FIX = Path(__file__).parent / "fixtures"

CASES = [
    # name, replay env, map env, default replay, default map, expected counts
    (
        "deafheaven",
        "OSU_TEST_DEAFHEAVEN_REPLAY",
        "OSU_TEST_DEAFHEAVEN_MAP",
        "~/Documents/Danser/Replays/ran27 playing inoqx - DEAFHEAVEN (namriee) [EXTREME COLLAB] (2026-06-22_18-09).osr",
        "~/Documents/Danser/Songs/2393752 inoqx - DEAFHEAVEN/inoqx - DEAFHEAVEN (namriee) [EXTREME COLLAB].osu",
        {"300": 503, "100": 74, "50": 8, "miss": 31},
    ),
    (
        "domino",
        "OSU_TEST_DOMINO_REPLAY",
        "OSU_TEST_DOMINO_MAP",
        "~/.var/app/sh.ppy.osu/data/osu/exports/ran27 playing Jessie J - Domino (Nightcore & Cut Ver.) (Kumocha) [Desire] (2026-06-29_23-40).osr",
        "~/Projects/code/osu-replay-critique/tmp_maps/943f12287fe5baa7ad9c02e99fc0b624.osu",
        {"300": 208, "100": 22, "50": 1, "miss": 0},
    ),
    (
        "aaaaa",
        "OSU_TEST_AAAA_REPLAY",
        "OSU_TEST_AAAA_MAP",
        "~/.var/app/sh.ppy.osu/data/osu/exports/ran27 playing Nashimoto Ui feat. Hatsune Miku - AaAaAaAAaAaAAa (XxX[xXx]XxX) [Hard Easy xD] (2026-06-22_19-30).osr",
        "~/Projects/code/osu-replay-critique/tmp_maps/aaaa_hard_easy_xd.osu",
        {"300": 65, "100": 0, "50": 0, "miss": 0},
    ),
]


def _resolve(name, default_replay, default_map):
    """Fixture first, then env, then default path; returns (replay, map) Paths."""
    replay, map_path = FIX / f"{name}.osr", FIX / f"{name}.osu"
    if replay.exists() and map_path.exists():
        return replay, map_path
    env = {"deafheaven": ("OSU_TEST_DEAFHEAVEN_REPLAY", "OSU_TEST_DEAFHEAVEN_MAP"),
           "domino": ("OSU_TEST_DOMINO_REPLAY", "OSU_TEST_DOMINO_MAP"),
           "aaaaa": ("OSU_TEST_AAAA_REPLAY", "OSU_TEST_AAAA_MAP")}[name]
    r_env, m_env = os.environ.get(env[0]), os.environ.get(env[1])
    if r_env and m_env:
        return Path(r_env).expanduser(), Path(m_env).expanduser()
    return (Path(default_replay).expanduser(), Path(default_map).expanduser())


@pytest.mark.parametrize("name,env_r,env_m,default_r,default_m,expected", CASES)
def test_golden(name, env_r, env_m, default_r, default_m, expected, tmp_path):
    replay, map_path = _resolve(name, default_r, default_m)
    if not replay.exists() or not map_path.exists():
        pytest.skip(f"fixtures for {name} not present")
    metrics = analyze(str(replay), str(map_path), tag=name,
                      outdir=str(tmp_path), console=False)
    det = metrics["counts_detected"]
    for k in ("300", "100", "50"):
        assert abs(det[k] - expected[k]) <= max(4, 0.02 * expected["300"]), \
            f"{k}: detected {det} vs recorded {expected}"
    assert abs(det["miss"] - expected["miss"]) <= 8, \
        f"miss: detected {det} vs recorded {expected}"


def test_scale_calibration_domino(tmp_path):
    """Domino's .osr claims DT but the frames are in map-time: the calibration
    must pick scale 1.0 and produce ~0 detected misses."""
    case = [c for c in CASES if c[0] == "domino"][0]
    replay, map_path = _resolve("domino", case[3], case[4])
    if not replay.exists() or not map_path.exists():
        pytest.skip("domino fixtures not present")
    metrics = analyze(str(replay), str(map_path), tag="domino",
                      outdir=str(tmp_path), console=False)
    assert metrics["counts_detected"]["miss"] == 0
    assert metrics["accuracy"] > 0.90


# ---------------------------------------------------------------- synth ----

SYNTH = [
    # name, (300, 100, 50), expected miss, extra assertions
    ("synth_clean", (17, 2, 1), 0, {}),
    ("synth_htm", (17, 2, 1), 0, {}),           # HT mod: frames at 4/3 scale
    ("synth_dt", (17, 2, 1), 0, {}),            # DT mod: frames at 2/3 scale
    ("synth_mismatch", (17, 2, 1), 20,          # 20 of 40 objects played
     {"map_version_mismatch": True, "failed_play": True}),
    ("synth_oooframes", (17, 2, 1), 0, {}),     # out-of-order trailing frame
]


@pytest.mark.parametrize("name,expected,expected_miss,extra", SYNTH,
                         ids=[s[0] for s in SYNTH])
def test_synthetic(name, expected, expected_miss, extra, tmp_path):
    replay, map_path = FIX / f"{name}.osr", FIX / f"{name}.osu"
    if not replay.exists() or not map_path.exists():
        pytest.skip(f"{name} not generated (run scripts/make_synthetic_fixtures.py)")
    metrics = analyze(str(replay), str(map_path), tag=name,
                      outdir=str(tmp_path), console=False)
    det = metrics["counts_detected"]
    assert (det["300"], det["100"], det["50"]) == expected, det
    assert det["miss"] == expected_miss, det
    assert metrics["whiffed_presses"] == 0
    for k, v in extra.items():
        assert metrics[k] is v


def test_anonymized_player_name():
    """Real fixtures must not contain the author's username."""
    r = slider.Replay.from_path(FIX / "aaaaa.osr", retrieve_beatmap=False)
    assert r.player_name == "TestPlayer"


def test_report_deterministic(tmp_path):
    """The report tier must work with no keys at all."""
    case = [c for c in CASES if c[0] == "aaaaa"][0]
    replay, map_path = _resolve("aaaaa", case[3], case[4])
    if not replay.exists() or not map_path.exists():
        pytest.skip("aaaaa fixtures not present")
    metrics = analyze(str(replay), str(map_path), tag="aaaaa",
                      outdir=str(tmp_path), console=False)
    from osu_critique.cli import render_report
    text = render_report(metrics)
    assert "Accuracy 100.0%" in text
    assert "Primary target" not in text or "No pattern" in text
