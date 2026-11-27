"""Leg descriptors on synthetic objects with a known answer."""
import math

from osu_critique.metrics import legs

R = 40.0


def _o(t, x, y, kind="Circle", **kw):
    d = {"t": t, "x": x, "y": y, "kind": kind}
    d.update(kw)
    return d


def _line(n, step_r, gap):
    return [_o(i * gap, 100 + i * step_r * R, 200) for i in range(n)]


def test_dist_classes():
    assert legs.dist_class(0.5) == "touching"
    assert legs.dist_class(2.0) == "close"
    assert legs.dist_class(4.0) == "medium"
    assert legs.dist_class(8.0) == "wide"


def test_flow_classes():
    assert legs.flow_class(None) == "none"
    assert legs.flow_class(10) == "flow"
    assert legs.flow_class(-90) == "angle"
    assert legs.flow_class(170) == "snap"


def test_tempo_uses_rhythm_ceilings():
    assert legs.tempo_class(150) == "fast"
    assert legs.tempo_class(200) == "mid"
    assert legs.tempo_class(400) == "slow"


def test_straight_line_is_flow_and_one_segment():
    objs = _line(8, 2.0, 100)
    d = legs.describe(objs, R)
    assert len(d["segments"]) == 1
    s = d["segments"][0]
    assert (s["dist"], s["flow"], s["tempo"]) == ("close", "flow", "fast")
    assert s["n"] == 7 and d["summary"]["coverage"] == 1.0


def test_back_and_forth_wide_is_snap_and_one_stray_corner_does_not_split():
    xs = [100, 100 + 8 * R] * 4
    objs = [_o(i * 150, x, 200) for i, x in enumerate(xs)]
    d = legs.describe(objs, R)
    assert len(d["segments"]) == 1 and d["segments"][0]["flow"] == "snap"
    assert d["segments"][0]["dist"] == "wide"


def test_short_legs_have_no_direction():
    objs = [_o(i * 100, 100 + (i % 2) * 0.5 * R, 200) for i in range(6)]
    rows = legs.legs(objs, R)
    assert all(r["flow"] == "none" and r["dist"] == "touching" for r in rows[1:])


def test_spinner_breaks_a_run():
    objs = _line(5, 2.0, 100) + [_o(600, 256, 192, "Spinner")] + _line(5, 2.0, 100)
    for i, o in enumerate(objs[6:]):
        o["t"] = 1000 + i * 100
    d = legs.describe(objs, R)
    assert len(d["segments"]) == 2
    assert all(r is None for r in (d["legs"][0], d["legs"][5], d["legs"][6]))


def test_turn_sign_clockwise_positive():
    # east then south: osu! y points down, so that is a clockwise turn
    objs = [_o(0, 100, 100), _o(100, 100 + 4 * R, 100), _o(200, 100 + 4 * R, 100 + 4 * R)]
    assert legs.legs(objs, R)[2]["turn_deg"] == 90.0


def test_slider_tail_is_leg_origin():
    objs = [_o(0, 100, 100, "Slider", end_x=100 + 6 * R, end_y=100),
            _o(300, 100 + 8 * R, 100)]
    assert math.isclose(legs.legs(objs, R)[1]["dist_r"], 2.0)


def test_beats_and_divisor_label():
    objs = _line(6, 2.0, 150)
    d = legs.describe(objs, R, beat_at=lambda t: 300.0)
    assert d["segments"][0]["label"].endswith("(1/2)")
