"""Golden regression tests: the pipeline must reproduce the game's recorded
hit counts on known-good replays.

The fixture replays/maps are the author's own files; point the env vars below
at them (or drop fixtures into tests/fixtures/ with matching names). Tests
skip when the files are absent, so the suite runs anywhere.
"""
import os
from pathlib import Path

import pytest

from osu_critique.report import analyze

FIX = Path(__file__).parent / "fixtures"

CASES = [
    # name, replay, map, expected: recorded counts dict (300/100/50/miss)
    (
        "deafheaven",
        "OSU_TEST_DEAFHEAVEN_REPLAY",
        "~/Documents/Danser/Replays/ran27 playing inoqx - DEAFHEAVEN (namriee) [EXTREME COLLAB] (2026-06-22_18-09).osr",
        "~/Documents/Danser/Songs/2393752 inoqx - DEAFHEAVEN/inoqx - DEAFHEAVEN (namriee) [EXTREME COLLAB].osu",
        {"300": 503, "100": 74, "50": 8, "miss": 31},
    ),
    (
        "domino-dt-flag",
        "OSU_TEST_DOMINO_REPLAY",
        "~/.var/app/sh.ppy.osu/data/osu/exports/ran27 playing Jessie J - Domino (Nightcore & Cut Ver.) (Kumocha) [Desire] (2026-06-29_23-40).osr",
        "~/Projects/code/osu-replay-critique/tmp_maps/943f12287fe5baa7ad9c02e99fc0b624.osu",
        {"300": 208, "100": 22, "50": 1, "miss": 0},
    ),
    (
        "aaaaa-perfect",
        "OSU_TEST_AAAA_REPLAY",
        "~/.var/app/sh.ppy.osu/data/osu/exports/ran27 playing Nashimoto Ui feat. Hatsune Miku - AaAaAaAAaAaAAa (XxX[xXx]XxX) [Hard Easy xD] (2026-06-22_19-30).osr",
        "~/Projects/code/osu-replay-critique/tmp_maps/aaaa_hard_easy_xd.osu",
        {"300": 65, "100": 0, "50": 0, "miss": 0},
    ),
]


def _resolve(name, env, default):
    if env:
        p = os.environ.get(env)
        if p:
            return Path(p).expanduser()
    d = Path(default).expanduser()
    if d.exists():
        return d
    # fixture dir fallback
    f = FIX / f"{name}.osu"
    return f


@pytest.mark.parametrize("name,env,default_replay,default_map,expected", CASES)
def test_golden(name, env, default_replay, default_map, expected, tmp_path):
    replay = _resolve(name, env, default_replay)
    map_path = _resolve(name + "-map", None, default_map)
    if not replay.exists() or not map_path.exists():
        pytest.skip(f"fixtures for {name} not present")
    metrics = analyze(str(replay), str(map_path), tag=name,
                      outdir=str(tmp_path), console=False)
    det = metrics["counts_detected"]
    # the pipeline must reproduce the game's counts (small tolerance for
    # slider-tick / near-window edge cases)
    for k in ("300", "100", "50"):
        assert abs(det[k] - expected[k]) <= max(4, 0.02 * expected["300"]), \
            f"{k}: detected {det} vs recorded {expected}"
    assert abs(det["miss"] - expected["miss"]) <= 8, \
        f"miss: detected {det} vs recorded {expected}"


def test_scale_calibration_domino(tmp_path):
    """Domino's .osr claims DT but the frames are in map-time: the calibration
    must pick scale 1.0 and produce ~0 detected misses."""
    replay = _resolve("domino-dt-flag", "OSU_TEST_DOMINO_REPLAY",
                      "~/.var/app/sh.ppy.osu/data/osu/exports/ran27 playing Jessie J - Domino (Nightcore & Cut Ver.) (Kumocha) [Desire] (2026-06-29_23-40).osr")
    map_path = _resolve("domino-dt-flag-map", None,
                        "~/Projects/code/osu-replay-critique/tmp_maps/943f12287fe5baa7ad9c02e99fc0b624.osu")
    if not replay.exists() or not map_path.exists():
        pytest.skip("domino fixtures not present")
    metrics = analyze(str(replay), str(map_path), tag="domino",
                      outdir=str(tmp_path), console=False)
    assert metrics["counts_detected"]["miss"] == 0
    assert metrics["accuracy"] > 0.90
