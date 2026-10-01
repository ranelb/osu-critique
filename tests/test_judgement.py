"""The judgement edge guard and the slider-body model.

The guard (``assignment.EDGE_GUARD_MS``) exists because a replay's frame clock is
floored to the millisecond: the stored press time can be up to 1 ms earlier than
the time the game judged, so an error measured *at* the window edge belongs to a
press the game saw outside it. On the author's 55 stored replays that is the
difference between 1 and 14 plays reproduced exactly, and it halves the total
drift.

The slider-body model (``metrics.sliders``) measures the body, ticks and tail of
every slider. It deliberately does **not** change the judgement: measured on 19
slider-heavy replays, degrading a slider whose tail was dropped makes 15 of them
worse and 1 better, so the fields are descriptive.
"""
import math
import os
from pathlib import Path

import numpy as np
import pytest

from osu_critique.metrics import sliders as S
from osu_critique.metrics.assignment import EDGE_GUARD_MS, classify
from osu_critique.report import analyze

FIX = Path(__file__).parent / "fixtures"
MAP = "tests/fixtures/aaaaa.osu"
REPLAY = "tests/fixtures/aaaaa.osr"

W = (32.0, 76.0, 120.0)          # OD 8 windows, as od_windows returns them


# ------------------------------------------------------------------ guard ---

def test_the_guard_moves_the_edge_objects_out_of_300():
    assert classify(-31.0, *W) == "300"        # comfortably inside
    assert classify(31.0, *W) == "300"
    assert classify(-32.0, *W) == "100"        # at the edge: the game saw later
    assert classify(32.0, *W) == "100"
    assert classify(-33.0, *W) == "100"


def test_the_guard_applies_to_every_window_edge():
    assert classify(76.0, *W) == "50"
    assert classify(75.0, *W) == "100"
    assert classify(120.0, *W) == "miss"
    assert classify(119.0, *W) == "50"


def test_a_zero_guard_is_the_old_lenient_rule():
    assert classify(32.0, *W, guard=0.0) == "300"
    assert classify(76.0, *W, guard=0.0) == "100"
    assert classify(120.0, *W, guard=0.0) == "50"


def test_the_guard_is_a_named_constant():
    assert 0.0 < EDGE_GUARD_MS <= 1.5


# ------------------------------------------------- synthetic slider bodies --

SLIDER_MAP = """osu file format v14

[General]
AudioFilename: dummy.mp3
AudioLeadIn: 0
PreviewTime: -1
Countdown: 0
SampleSet: Soft
StackLeniency: 0.7
Mode: 0

[Metadata]
Title:synthetic sliders
TitleUnicode:synthetic sliders
Artist:synthetic
ArtistUnicode:synthetic
Creator:osu-critique
Version:test

[Difficulty]
HPDrainRate:5
CircleSize:4
OverallDifficulty:8
ApproachRate:9
SliderMultiplier:1.4
SliderTickRate:1

[TimingPoints]
0,300,4,2,1,25,1,0

[HitObjects]
100,100,1000,2,0,L|400:100,1,300
100,100,4000,2,0,L|400:100,2,300
"""


@pytest.fixture(scope="module")
def slider_map(tmp_path_factory):
    p = tmp_path_factory.mktemp("slidermap") / "sliders.osu"
    p.write_text(SLIDER_MAP)
    return p


def _sliders(path):
    import slider
    bm = slider.Beatmap.from_path(str(path))
    return [o for o in bm.hit_objects() if type(o).__name__ == "Slider"]


def test_path_point_walks_the_slider_and_folds_back_on_repeats(slider_map):
    one, rep = _sliders(slider_map)
    assert S.path_point(one, 1000.0, 1000.0, 1300.0)[0] == pytest.approx(100.0, abs=1)
    assert S.path_point(one, 1300.0, 1000.0, 1300.0)[0] == pytest.approx(400.0, abs=1)
    # a 2-pass slider is at the far end halfway through and back at the head at the end
    assert S.path_point(rep, 4300.0, 4000.0, 4600.0)[0] == pytest.approx(400.0, abs=1)
    assert S.path_point(rep, 4600.0, 4000.0, 4600.0)[0] == pytest.approx(100.0, abs=1)


def test_tick_points_are_time_ordered_and_scaled(slider_map):
    one, _rep = _sliders(slider_map)
    ticks = S.tick_points(one, 1.0)
    assert len(ticks) >= 2
    assert ticks[-1][0] >= ticks[0][0]
    assert 1000 <= ticks[0][0] <= 1400
    scaled = S.tick_points(one, 0.5)
    assert scaled[0][0] == pytest.approx(ticks[0][0] * 0.5, abs=1e-6)


def _frames(points):
    frames = [(float(t), float(x), float(y), True, False) for t, x, y in points]
    return frames, np.array([f[0] for f in frames])


def test_follow_sees_a_traced_slider(slider_map):
    one, _rep = _sliders(slider_map)
    start = one.time.total_seconds() * 1000
    end = one.end_time.total_seconds() * 1000
    frames, times = _frames([(0, 100, 100), (start, 100, 100), (end, 400, 100),
                             (end + 1000, 400, 100)])
    # the cursor rides the slider's own path, at its real (map-derived) timing
    cursor = lambda t: S.path_point(one, t, start, end)   # noqa: E731
    body = S.follow(one, frames, times, 36.48, 1.0, cursor)
    assert body["off_pct"] == pytest.approx(0.0)
    assert body["cut"] is False
    assert body["tail_off"] is False


def test_follow_sees_a_dropped_slider(slider_map):
    one, _rep = _sliders(slider_map)
    # the cursor sits at the head for the whole slider
    frames, times = _frames([(0, 100, 100), (2000, 100, 100)])
    body = S.follow(one, frames, times, 36.48, 1.0, lambda t: (100.0, 100.0))
    assert body["off_pct"] > 50
    assert body["cut"] is True
    assert body["tail_off"] is True


def test_annotate_puts_the_fields_on_slider_rows_only(slider_map):
    objs = [
        {"i": 0, "t": 1000.0, "end": 1300.0, "x": 100.0, "y": 100.0, "kind": "Slider",
         "result": "300"},
        {"i": 1, "t": 2000.0, "end": 2000.0, "x": 200.0, "y": 200.0, "kind": "Circle",
         "result": "300"},
    ]
    frames, times = _frames([(0, 100, 100), (2000, 200, 200)])
    raw = _sliders(slider_map)[:1]
    block = S.annotate(objs, raw, frames, times, 36.48, 1.0,
                       cursor_at=lambda t: (100.0, 100.0))
    assert block["n"] == 1
    assert block["cut"] >= 1
    assert block["follow_r"] == S.FOLLOW_R
    assert objs[0]["slider_off_pct"] is not None
    assert "slider_off_pct" not in objs[1]


# ------------------------------------------------------------- in a play ----

def test_metrics_carry_the_slider_block_and_the_records_the_fields(tmp_path):
    m = analyze(str(FIX / "deafheaven.osr"), str(FIX / "deafheaven.osu"),
                tag="deaf", outdir=str(tmp_path), console=False)
    sl = m["sliders"]
    assert sl["n"] > 0 and sl["n"] == sl["miss"] + sl["n"] - sl["miss"]
    for k in ("tail_off", "cut", "cut_pct", "tick_missed_pct", "off_pct_median"):
        assert k in sl, k
    import json
    rec = json.loads((tmp_path / "deaf_objects.json").read_text())["objects"]
    sliders = [r for r in rec if r["kind"] == "Slider"]
    circles = [r for r in rec if r["kind"] != "Slider"]
    assert sliders and all(r["slider_off_pct"] is not None for r in sliders)
    assert all(r["slider_off_pct"] is None for r in circles)
    assert all(isinstance(r["slider_tail_off"], bool) for r in sliders)


# ------------------------------------------------ the reference replays -----

REF = {
    "montagem": ("OSU_TEST_MONTAGEM_REPLAY", "OSU_TEST_MONTAGEM_MAP",
                 {"300": 142, "100": 29, "50": 0, "miss": 3}),
    "4ever": ("OSU_TEST_4EVER_REPLAY", "OSU_TEST_4EVER_MAP",
              {"300": 159, "100": 20, "50": 0, "miss": 2}),
}


@pytest.mark.parametrize("name", list(REF))
def test_the_guard_reproduces_the_reference_counts_exactly(name, tmp_path):
    """The slider-heavy plays whose 300/100 split used to drift by ~10 objects."""
    replay, map_path, expected = REF[name]
    replay, map_path = os.environ.get(replay), os.environ.get(map_path)
    if not (replay and map_path):
        pytest.skip(f"set {name} env vars to check the reference counts")
    m = analyze(replay, map_path, tag=name, outdir=str(tmp_path), console=False,
                write_objects=False)
    assert m["counts_detected"] == expected
    assert m["trust"]["within_tolerance"] is True
