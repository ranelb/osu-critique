"""The miss-autopsy block: shape classes, arrival margin, legs, stutter, misses.

Reference numbers were published for two real replays (docs/ROADMAP.md item 2):

- MONTAGEM BATCHI: near-reversal chains 17.5 % off 300 vs cornered 0 %, the three
  misses at 1.32/1.30/1.07 r at the note with presses +5/+2/-3 ms, heading error
  median 2 deg / p90 8 deg / max 14 deg.
- 4ever: reversals 9.1 % vs cornered 0 %, the two misses at 1.20 r (press -9 ms,
  aim 1.26 r) and 0.98 r (press +16 ms, aim 1.07 r), heading 2/6/11 deg.

Those replays are the author's and are not committed; the checks run only where
`OSU_TEST_MONTAGEM_REPLAY` / `_MAP` (and the 4ever pair) are set. The synthetic
fixtures below pin the helpers without them.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from osu_critique.metrics import autopsy as AU
from osu_critique.report import analyze

FIX = Path(__file__).parent / "fixtures"
MAP = "tests/fixtures/aaaaa.osu"
REPLAY = "tests/fixtures/aaaaa.osr"


def obj(i, t, x=100.0, y=100.0, kind="Circle"):
    return {"i": i, "t": float(t), "end": float(t), "x": float(x), "y": float(y),
            "kind": kind}


def row(i, result="300", error=None, aim=None, spacing_r=None, angle=None,
        kind="Circle", t=1000.0):
    return {"i": i, "t": t, "result": result, "error": error, "aim": aim,
            "spacing_r": spacing_r, "angle_deg": angle, "kind": kind}


# ---------------------------------------------------------- shape classes ---

def test_shape_class_labels_a_reversal_chain():
    # a zig-zag: every turn is a full reversal (180 deg)
    objs = [obj(i, 1000 + 100 * i, x=100.0 if i % 2 == 0 else 400.0)
            for i in range(5)]
    assert AU.shape_class(objs, 2) == "near-reversal chain"


def test_shape_class_labels_a_box():
    # a square walked around: four 90 deg corners
    corners = [(100, 100), (300, 100), (300, 300), (100, 300), (100, 100),
               (300, 100), (300, 300)]
    objs = [obj(i, 1000 + 100 * i, x=float(x), y=float(y))
            for i, (x, y) in enumerate(corners)]
    assert AU.shape_class(objs, 3) == "cornered (box)"


def test_shape_class_labels_flow_and_none_at_the_edges():
    # a straight line + gentle kinks: no sharp turns anywhere
    objs = [obj(i, 1000 + 100 * i, x=100.0 + 60.0 * i, y=100.0 + 2.0 * i)
            for i in range(6)]
    assert AU.shape_class(objs, 2) == "flow (arc/line)"
    assert AU.shape_class(objs, 0) is None          # no room for a 5-note window
    assert AU.shape_class(objs, 1) is None
    assert AU.shape_class(objs, len(objs) - 2) is None


def test_shapes_gate_rates_by_n():
    objs = [obj(i, 1000 + 100 * i, x=100.0 if i % 2 == 0 else 400.0)
            for i in range(6)]                 # 2 windows: too few to report
    results = [row(i, result="100" if i == 2 else "300") for i in range(6)]
    block = AU.shapes(objs, results)
    cls = {c["class"]: c for c in block["classes"]}
    assert cls["near-reversal chain"]["n"] == 2
    assert cls["near-reversal chain"]["non300"] == 1
    assert cls["near-reversal chain"]["non300_rate"] == pytest.approx(0.5)
    assert cls["near-reversal chain"]["reported"] is False     # n < MIN_SHAPE_N


def test_shapes_use_the_aim_rows_for_the_arrival_column():
    objs = [obj(i, 1000 + 100 * i, x=100.0 if i % 2 == 0 else 400.0)
            for i in range(14)]
    results = [row(i) for i in range(14)]
    aim_rows = [{"i": i, "d": 0.25 * i} for i in range(14)]
    block = AU.shapes(objs, results, aim_rows=aim_rows)
    rev = block["classes"][0]
    assert rev["mean_d_r"] is not None and rev["mean_d_r"] > 0
    assert AU.shapes(objs, results)["classes"][0]["mean_d_r"] is None


# -------------------------------------------------------------- margins -----

def test_arrival_margin_reports_the_rim_tail():
    results = [row(i, aim=36.48 * r) for i, r in enumerate([0.2, 0.4, 0.9, 1.1])]
    m = AU.arrival_margin(results, 36.48)
    assert m["n"] == 4
    assert m["median"] == pytest.approx(0.65, abs=1e-9)
    assert m["max"] == pytest.approx(1.1, abs=1e-9)
    assert m["beyond_rim_pct"] == pytest.approx(50.0)   # 0.9 and 1.1 are > 0.8


def test_press_vs_arrival_is_negative_when_the_press_beats_the_cursor():
    results = [row(0, error=-16.0), row(1, error=+20.0)]
    aim_rows = [{"i": 0, "peak_off": +10.0}, {"i": 1, "peak_off": 0.0}]
    out = AU.press_vs_arrival(results, aim_rows)
    assert out["n"] == 2
    assert out["median"] == pytest.approx(-3.0)         # (-16-10, +20-0) -> -3
    assert out["pressed_before_arrival_pct"] == pytest.approx(50.0)


# ----------------------------------------------------------------- legs -----

def _frames(points):
    return ([(float(t), float(x), float(y), False, False) for t, x, y in points],
            np.array([float(t) for t, _x, _y in points]))


def test_legs_measure_heading_and_efficiency():
    # two objects 300 px apart in x; the cursor travels straight between them
    objs = [obj(0, 1000, x=100.0, y=100.0), obj(1, 2000, x=400.0, y=100.0)]
    frames, times = _frames([(1000, 100, 100), (1500, 250, 100), (2000, 400, 100)])
    out = AU.legs(objs, frames, times, 36.48)
    assert out["n"] == 1
    assert out["heading_err_deg"]["median"] == pytest.approx(0.0, abs=1e-6)
    assert out["path_efficiency"]["median"] == pytest.approx(1.0, abs=1e-6)


def test_legs_flag_a_detour():
    # a detour shows up in path efficiency, not heading: the heading compares the
    # cursor at the two notes, which a symmetric arc leaves pointing the right way
    objs = [obj(0, 1000, x=100.0, y=100.0), obj(1, 2000, x=400.0, y=100.0)]
    frames, times = _frames([(1000, 100, 100), (1500, 250, 300), (2000, 400, 100)])
    out = AU.legs(objs, frames, times, 36.48)
    assert out["path_efficiency"]["median"] < 0.75
    assert out["heading_err_deg"]["median"] == pytest.approx(0.0, abs=1e-6)


def test_legs_skip_short_and_coincident_legs():
    # a 5 px hop has no meaningful direction: it must not enter the table
    objs = [obj(0, 1000, x=100.0, y=100.0), obj(1, 1200, x=105.0, y=104.0),
            obj(2, 1400, x=400.0, y=100.0)]
    frames, times = _frames([(1000, 100, 100), (1100, 105, 104), (1300, 250, 100),
                             (1400, 400, 100)])
    out = AU.legs(objs, frames, times, 36.48)
    assert out["n"] == 1                              # only the long leg counts


# --------------------------------------------------------------- stutter ----

def test_stutter_counts_early_presses_far_from_the_note():
    objs = [obj(0, 5000, x=400.0, y=100.0)]
    frames, times = _frames([(0, 100, 100), (6000, 100, 100)])
    early = [(4900.0, "A")]        # 100 ms early, cursor 300 px away (= 8 r)
    on_time = [(5000.0, "A")]
    assert AU.stutter(frames, times, early, objs, 36.48)["n"] == 1
    assert AU.stutter(frames, times, on_time, objs, 36.48)["n"] == 0


# --------------------------------------------------------------- misses -----

def test_a_miss_records_the_press_that_missed_it():
    objs = [obj(0, 1000), obj(1, 5000, x=400.0)]
    frames, times = _frames([(0, 100, 100), (5000, 100, 100), (6000, 100, 100)])
    results = [row(0, t=1000.0), row(1, result="miss", t=5000.0, spacing_r=8.4)]
    aim_rows = [{"i": 0, "d": 0.1, "dmin": 0.05, "peak_off": 0.0, "speed": 1.0},
                {"i": 1, "d": 1.20, "dmin": 0.9, "peak_off": 0.0, "speed": 2.0}]
    block = AU.misses(results, objs, [(4985.0, "B")], aim_rows, 36.48, 250.0,
                      frames=frames, times=times)
    assert block["n"] == 1
    m = block["rows"][0]
    assert m["i"] == 1 and m["d_r"] == 1.20
    assert m["press_ms"] == pytest.approx(-15.0)       # press 15 ms early
    assert m["aim_at_press_r"] == pytest.approx(300 / 36.48, rel=1e-3)
    assert m["gap_r"] == 8.4


def test_misses_are_ordered_worst_first_and_capped():
    objs = [obj(i, 1000 + 100 * i) for i in range(4)]
    results = [row(i, result="miss") for i in range(4)]
    aim_rows = [{"i": 0, "d": 0.5, "dmin": 0.4, "peak_off": 0, "speed": 1.0},
                {"i": 1, "d": 1.5, "dmin": 1.2, "peak_off": 0, "speed": 1.0},
                {"i": 2, "d": 0.9, "dmin": 0.8, "peak_off": 0, "speed": 1.0},
                {"i": 3, "d": 1.1, "dmin": 1.0, "peak_off": 0, "speed": 1.0}]
    block = AU.misses(results, objs, [], aim_rows, 36.48, 250.0, limit=3)
    assert block["n"] == 4 and len(block["rows"]) == 3
    assert [m["i"] for m in block["rows"]] == [1, 3, 2]


# ------------------------------------------------------------- pipeline -----

def test_the_block_is_in_every_analysis(tmp_path):
    m = analyze(REPLAY, MAP, tag="aaaaa", outdir=str(tmp_path), console=False)
    au = m["autopsy"]
    assert au and au["shapes"]["classes"]
    assert au["legs"]["n"] > 0
    assert au["arrival_margin_r"]["n"] > 0
    assert au["stutter"]["presses"] > 0
    json.dumps(au, allow_nan=False)
    on_disk = json.loads((tmp_path / "aaaaa_metrics.json").read_text())
    assert on_disk["autopsy"]["shapes"]["classes"] == au["shapes"]["classes"]


def test_no_autopsy_flag_skips_the_block(tmp_path):
    m = analyze(REPLAY, MAP, tag="noau", outdir=str(tmp_path), console=False,
                write_autopsy=False)
    assert m["autopsy"] is None


def test_cli_no_autopsy_end_to_end(tmp_path):
    from osu_critique.cli import main
    assert main(["analyze", REPLAY, MAP, "cliau", "--no-autopsy",
                 "--outdir", str(tmp_path)]) == 0
    m = json.loads((tmp_path / "cliau_metrics.json").read_text())
    assert m["autopsy"] is None
    assert m["aim_mode"] is not None


def test_report_and_console_render_the_block(tmp_path, capsys):
    from osu_critique.cli import render_report
    from osu_critique.report import console_summary
    m = analyze(REPLAY, MAP, tag="aaaaa", outdir=str(tmp_path), console=False)
    text = render_report(m)
    assert "## Miss autopsy" in text
    assert "shapes (5-note windows)" in text
    console_summary(m)
    out = capsys.readouterr().out
    assert "shapes (5-note windows, off-300)" in out


def test_worst_windows_figure_is_written(tmp_path):
    pytest.importorskip("matplotlib")
    analyze(REPLAY, MAP, tag="aaaaa", outdir=str(tmp_path), console=False,
            do_charts=True)
    assert (tmp_path / "aaaaa_windows.png").exists()


def test_rx_play_reports_cursor_only(tmp_path):
    """Under RX there are no taps: the tap-derived sections are absent, not zero."""
    rx, rx_map = FIX / "synth_rx.osr", FIX / "synth_rx.osu"
    if not rx.exists():
        pytest.skip("synth_rx not generated")
    au = analyze(str(rx), str(rx_map), tag="rx", outdir=str(tmp_path),
                 console=False)["autopsy"]
    assert au["is_relax"] is True
    assert au["arrival_margin_r"] is None
    assert au["press_vs_arrival_ms"] is None
    assert au["stutter"] is None
    assert au["legs"] is not None              # the cursor still has legs
    assert au["shapes"]["classes"]             # zig-zag fixture: all reversals
    assert au["shapes"]["classes"][0]["class"] == "near-reversal chain"
    assert au["misses"]["n"] == 60


# ------------------------------------------------- the acceptance replays --

CASES = {
    "montagem": {
        "env": ("OSU_TEST_MONTAGEM_REPLAY", "OSU_TEST_MONTAGEM_MAP"),
        "reversal": 17.5, "cornered": 0.0,
        "misses": [("Slider", 1.32, 5.0, 1.45), ("Circle", 1.30, 2.0, 1.40),
                   ("Slider", 1.07, -3.0, 1.08)],
        "heading": (2.0, 8.0, 14.0),
    },
    "4ever": {
        "env": ("OSU_TEST_4EVER_REPLAY", "OSU_TEST_4EVER_MAP"),
        "reversal": 9.1, "cornered": 0.0,
        "misses": [("Circle", 1.20, -9.0, 1.26), ("Slider", 0.98, 16.0, 1.07)],
        "heading": (2.0, 6.0, 11.0),
    },
}


@pytest.mark.parametrize("name", list(CASES))
def test_acceptance_on_the_reference_replays(name, tmp_path):
    """docs/ROADMAP.md item 2 acceptance (within rounding)."""
    import os
    case = CASES[name]
    replay, map_path = (os.environ.get(case["env"][0]),
                        os.environ.get(case["env"][1]))
    if not (replay and map_path):
        pytest.skip(f"set {case['env'][0]} / {case['env'][1]} to the author's "
                    f"{name} export + map")
    m = analyze(replay, map_path, tag=name, outdir=str(tmp_path), console=False,
                write_objects=False)
    au = m["autopsy"]
    classes = {c["class"]: c for c in au["shapes"]["classes"]}
    rev = classes["near-reversal chain"]
    corner = classes.get("cornered (box)")
    assert rev["non300_rate"] * 100 == pytest.approx(case["reversal"], abs=0.5)
    assert corner is not None
    assert corner["non300_rate"] == pytest.approx(case["cornered"] / 100, abs=1e-9)

    got = au["misses"]["rows"]
    assert len(got) == len(case["misses"])
    for g, (kind, d_r, press_ms, aim_r) in zip(got, case["misses"]):
        assert g["kind"] == kind
        assert g["d_r"] == pytest.approx(d_r, abs=0.02)
        assert g["press_ms"] == pytest.approx(press_ms, abs=1.5)
        assert g["aim_at_press_r"] == pytest.approx(aim_r, abs=0.02)

    h = au["legs"]["heading_err_deg"]
    assert h["median"] == pytest.approx(case["heading"][0], abs=1.0)
    assert h["p90"] == pytest.approx(case["heading"][1], abs=1.5)
    assert h["max"] <= case["heading"][2] + 1.0
