"""Geometric pattern segments (metrics/geometry.py).

Two layers: small hand-built object lists that pin each rule, and the generated
fixtures in tests/fixtures/patterns/ (scripts/make_pattern_fixtures.py), which
have the right answer by construction and go through the real .osu parser.
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

from osu_critique.metrics import geometry as G

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "patterns"
R = 36.5


def _objs(points, gap=166.0, kind="Circle"):
    return [{"t": 1000.0 + i * gap, "x": float(x), "y": float(y), "kind": kind}
            for i, (x, y) in enumerate(points)]


def _polygon(k, side_r=3.2, laps=2, cw=True, center=(256, 192)):
    big = side_r * R / (2 * math.sin(math.pi / k))
    sign = 1.0 if cw else -1.0
    verts = [(center[0] + big * math.cos(sign * 2 * math.pi * j / k),
              center[1] + big * math.sin(sign * 2 * math.pi * j / k)) for j in range(k)]
    return [verts[i % k] for i in range(k * laps + 1)]


def _shapes(objs):
    return [(s["shape"], s["start"], s["end"]) for s in G.classify(objs, R)]


# ------------------------------------------------------------------ cycles --

@pytest.mark.parametrize("k,name", [(3, "triangle"), (4, "square"),
                                    (5, "pentagon"), (6, "hexagon")])
def test_regular_polygons_are_named_by_their_corner_count(k, name):
    segs = G.classify(_objs(_polygon(k)), R)
    assert [s["shape"] for s in segs] == [name]
    assert segs[0]["period"] == k


def test_winding_follows_the_screen_not_the_maths():
    # osu! y points down: increasing angle is clockwise as drawn
    assert G.classify(_objs(_polygon(3, cw=True)), R)[0]["dir"] == "cw"
    assert G.classify(_objs(_polygon(3, cw=False)), R)[0]["dir"] == "ccw"


def test_one_lap_is_not_a_triangle():
    # any three notes form a triangle: a shape needs the positions to repeat, and
    # a lap and a half (a b c a b) is mostly chance on a real map
    assert G.classify(_objs(_polygon(3, laps=1)), R) == []
    assert G.classify(_objs(_polygon(3, laps=2)[:5]), R) == []
    assert G.classify(_objs(_polygon(3, laps=2)[:6]), R)[0]["shape"] == "triangle"


def test_a_pentagram_is_a_star_not_a_pentagon():
    pentagon = _polygon(5, side_r=6.5, laps=2)
    big = 6.5 * R / (2 * math.sin(2 * math.pi / 5))
    verts = [(256 + big * math.cos(2 * math.pi * k / 5), 192 + big * math.sin(2 * math.pi * k / 5))
             for k in (0, 2, 4, 1, 3)]
    got = G.classify(_objs([verts[i % 5] for i in range(11)]), R)
    assert got[0]["shape"] == "star" and got[0]["dir"] == "cw"
    assert G.classify(_objs(pentagon), R)[0]["shape"] == "pentagon"


def test_stack_needs_notes_on_top_of_each_other():
    assert _shapes(_objs([(100, 100), (101, 100)] * 3))[0][0] == "stack"
    assert _shapes(_objs([(100, 100), (100 + 3 * R, 100)] * 3))[0][0] == "back_and_forth"


def test_a_rectangle_is_not_a_square():
    pts = [(100, 100), (100 + 5 * R, 100), (100 + 5 * R, 100 + 2.5 * R), (100, 100 + 2.5 * R)]
    segs = G.classify(_objs([pts[i % 4] for i in range(9)]), R)
    assert segs[0]["shape"] == "rectangle"


def test_a_bowtie_is_not_a_square():
    # same four corners, visited in crossing order
    pts = [(100, 100), (100 + 3 * R, 100 + 3 * R), (100 + 3 * R, 100), (100, 100 + 3 * R)]
    segs = G.classify(_objs([pts[i % 4] for i in range(9)]), R)
    assert segs[0]["shape"] == "quad"


def test_hand_placed_polygon_is_still_found():
    # every vertex drifts a few pixels from lap to lap
    pts = [(x + (i % 3), y - (i % 2) * 2) for i, (x, y) in enumerate(_polygon(3, laps=3))]
    assert G.classify(_objs(pts), R)[0]["shape"] == "triangle"


# ------------------------------------------------------------- fits/turns --

def test_straight_run_is_a_line_and_a_short_one_is_not():
    line = [(50 + i * 3 * R, 100 + i * 20) for i in range(5)]
    assert _shapes(_objs(line)) == [("line", 0, 4)]
    # four notes in a row is mostly chance (a gentle curve fits within tolerance)
    assert G.classify(_objs(line[:4]), R) == []


def test_line_tolerates_hand_placement_but_not_a_bend():
    wobbly = [(50 + i * 3 * R, 100 + (8 if i % 2 else -8)) for i in range(6)]
    assert G.classify(_objs(wobbly), R)[0]["shape"] == "line"
    bent = [(50, 100), (150, 100), (250, 100), (330, 180), (330, 280), (330, 380)]
    # the first three notes are straight, but a bend ends the run before it is a line
    assert all(s["shape"] != "line" or s["end"] < 4 for s in G.classify(_objs(bent), R))


def test_notes_closer_than_1_5_radii_have_no_direction():
    dense = [(100 + i * 0.9 * R, 100) for i in range(8)]
    assert G.classify(_objs(dense), R) == []


def test_zigzag_alternates_corners_of_similar_size():
    pts, x, y = [(100, 200)], 100, 200
    for i in range(7):
        h = math.radians(50 if i % 2 == 0 else -50)
        x, y = x + 3 * R * math.cos(h), y + 3 * R * math.sin(h)
        pts.append((x, y))
    assert G.classify(_objs(pts), R)[0]["shape"] == "zigzag"


def test_back_and_forth_returns_to_the_same_two_spots():
    a, b = (100, 200), (100 + 4 * R, 200)
    assert G.classify(_objs([a, b, a, b, a, b]), R)[0]["shape"] == "back_and_forth"
    # four notes that merely turn sharply twice are a loose zigzag, not a shuttle
    sharp = [(100, 200), (100 + 4 * R, 230), (100 + 0.5 * R, 300), (100 + 4 * R, 330)]
    assert all(s["shape"] != "back_and_forth" for s in G.classify(_objs(sharp), R))


def _circle(n, side_r=2.4, closed=True):
    step = 2 * math.pi / n
    big = side_r * R / (2 * math.sin(step / 2))
    return [(256 + big * math.cos(step * i), 192 + big * math.sin(step * i))
            for i in range(n + (1 if closed else 0))]


def test_a_full_lap_is_a_circle_and_part_of_one_is_an_arc():
    full = G.classify(_objs(_circle(12)), R)
    assert [s["shape"] for s in full] == ["circle"] and abs(full[0]["sweep"]) >= 300
    part = G.classify(_objs(_circle(12)[:6]), R)
    assert [s["shape"] for s in part] == ["arc"] and abs(part[0]["sweep"]) < 300


def test_arc_winding_is_signed():
    assert G.classify(_objs(_circle(12)), R)[0]["dir"] == "cw"
    assert G.classify(_objs(_circle(12)[::-1]), R)[0]["dir"] == "ccw"


def test_look_ahead_prefers_the_later_start_that_explains_more():
    # two stray notes that happen to lead into a circle must not eat its start
    lead = [(256 + 90, 192 + 40), (256 + 100, 192 + 80)]
    segs = G.classify(_objs(lead + _circle(12)), R)
    assert segs[-1]["shape"] == "circle" and segs[-1]["n"] >= 12


# ----------------------------------------------------------------- outputs --

def test_segments_do_not_overlap_and_carry_their_timing():
    objs = _objs(_polygon(3) + [(40, 40), (400, 300)] + _polygon(4, center=(300, 200)))
    segs = G.classify(objs, R, beat_ms=333.3)
    for a, b in zip(segs, segs[1:]):
        assert a["end"] < b["start"]
    seg = segs[0]
    assert seg["rate_ms"] == pytest.approx(166.0)
    assert seg["beats"] == pytest.approx(166.0 / 333.3)
    assert seg["spacing_r"] == pytest.approx(3.2, abs=0.1)
    assert seg["t0"] == objs[seg["start"]]["t"]


def test_sliders_are_flagged_not_hidden():
    objs = _objs(_polygon(3, laps=3))
    objs[4]["kind"] = "Slider"
    assert G.classify(objs, R)[0]["has_sliders"] is True


def test_label_objects_and_summary_agree():
    objs = _objs(_polygon(3) + [(40, 40), (400, 300)])
    segs = G.classify(objs, R)
    G.label_objects(objs, segs)
    assert [o["shape"] for o in objs[:7]] == ["triangle"] * 7
    assert objs[-1]["shape"] is None
    summary = G.summarize(segs, len(objs))
    assert summary["covered"] == 7 and summary["shapes"]["triangle"]["segments"] == 1
    assert summary["coverage"] == pytest.approx(7 / len(objs))


def test_empty_and_tiny_maps_do_not_crash():
    for n in (0, 1, 2, 3):
        assert G.classify(_objs([(100 + 50 * i, 100) for i in range(n)]), R) == []
    assert G.summarize([], 0)["coverage"] == 0.0


# ----------------------------------------------------------- the fixtures --

def _load(name, slider_tails=None):
    spec = importlib.util.spec_from_file_location(
        "eval_patterns", ROOT / "scripts" / "eval_patterns.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run(FIX / f"{name}.osu", verbose=False, slider_tails=slider_tails)


@pytest.mark.parametrize("name", ["geo_clean", "geo_stream", "geo_wide"])
def test_generated_maps_are_read_back_exactly(name):
    res, _segs, labels = _load(name)
    assert len(res["found"]) == len(labels["blocks"]) >= 16
    assert not res["mislabelled"] and not res["missed"] and not res["wrong_dir"]
    assert not res["false_positive"]


def test_hand_placement_noise_costs_a_little_not_a_lot():
    # ~0.28 radii of jitter per axis is far sloppier than any real mapper
    res, _segs, labels = _load("geo_sloppy")
    assert len(res["found"]) >= 10 and not res["wrong_dir"] and not res["false_positive"]


def test_irregular_filler_is_left_unlabelled():
    res, segs, _labels = _load("geo_junk")
    assert len(res["false_positive"]) <= 1
    assert sum(s["n"] for s in segs) / 400 < 0.03


# ------------------------------------------------- slider tails (phase C) --

def test_slider_tails_default_is_off_and_off_is_the_old_behaviour():
    assert G.SLIDER_TAILS_DEFAULT is False
    res, _s, labels = _load("geo_tail")
    assert len(res["found"]) == 0 and len(labels["blocks"]) == 17


@pytest.mark.parametrize("name", ["geo_tail", "geo_head", "geo_tail_sloppy"])
def test_flag_reads_shapes_drawn_through_slider_ends(name):
    res, _segs, labels = _load(name, slider_tails=True)
    assert len(res["found"]) == len(labels["blocks"])
    assert not res["mislabelled"] and not res["wrong_dir"] and not res["false_positive"]


def test_flag_does_not_invent_shapes_in_slider_junk():
    _res, segs, _labels = _load("geo_tail_junk", slider_tails=True)
    assert sum(s["n"] for s in segs) / 400 < 0.03


@pytest.mark.parametrize("name", ["geo_clean", "geo_sloppy", "geo_stream", "geo_wide", "geo_junk"])
def test_flag_changes_nothing_on_circle_only_maps(name):
    off = _load(name, slider_tails=False)[1]
    on = _load(name, slider_tails=True)[1]
    assert [(s["shape"], s["start"], s["end"]) for s in off] == \
           [(s["shape"], s["start"], s["end"]) for s in on]
    assert all("nodes" not in s for s in on)


def test_fixtures_regenerate_byte_for_byte(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "make_pattern_fixtures", ROOT / "scripts" / "make_pattern_fixtures.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    monkeypatch.setattr(gen, "OUT", tmp_path)
    gen.main()
    for path in sorted(tmp_path.iterdir()):
        assert path.read_text() == (FIX / path.name).read_text(), path.name
    assert json.loads((FIX / "geo_clean.labels.json").read_text())["blocks"]
