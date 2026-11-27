"""Smooth dense paths on synthetic notes with a known answer."""
import math

from osu_critique.metrics import curves

R = 40.0


def _o(t, x, y, kind="Circle"):
    return {"t": t, "x": x, "y": y, "kind": kind}


def _arc(n, step_r, turn_deg, gap=80, t0=0, x0=200.0, y0=200.0, h0=0.0):
    out, x, y, h = [], x0, y0, h0
    for i in range(n):
        out.append(_o(t0 + i * gap, x, y))
        x += step_r * R * math.cos(math.radians(h))
        y += step_r * R * math.sin(math.radians(h))
        h += turn_deg
    return out


def _shapes(objs, **kw):
    return [(s["shape"], s["form"]) for s in curves.find(objs, R, **kw)]


def test_gentle_arc_is_curvy_stream():
    assert _shapes(_arc(10, 1.5, 12)) == [("curvy_stream", "arc")]


def test_closed_ring_is_circle():
    assert _shapes(_arc(12, 1.5, 30)) == [("circle", "circle")]


def test_straight_dense_run_is_line_not_curvy():
    assert _shapes(_arc(10, 1.5, 0)) == [("line", "straight")]


def test_s_curve_splits_at_the_inflection():
    objs = _arc(8, 1.5, 12)
    last = objs[-1]
    objs += _arc(8, 1.5, -12, t0=8 * 80, x0=last["x"], y0=last["y"], h0=84)[1:]
    got = _shapes(objs)
    assert len(got) == 2 and all(s == "curvy_stream" for s, _ in got)


def test_wide_jumps_find_nothing():
    objs = [_o(i * 150, 100 + (i % 2) * 8 * R, 100 + (i % 3) * 3 * R) for i in range(12)]
    assert curves.find(objs, R) == []


def test_slow_notes_find_nothing():
    assert curves.find(_arc(10, 1.5, 12, gap=300), R) == []


def test_four_note_square_loop_is_not_a_curve():
    pts = [(0, 0), (1.9, 0), (1.9, 1.9), (0, 1.9)] * 3
    objs = [_o(i * 100, 100 + x * R, 100 + y * R) for i, (x, y) in enumerate(pts)]
    assert curves.find(objs, R) == []


def test_corner_ends_the_run():
    a = _arc(8, 1.5, 0)
    b = _arc(8, 1.5, 0, t0=8 * 80, x0=a[-1]["x"], y0=a[-1]["y"] + 1.5 * R, h0=90)
    assert [s for s, _ in _shapes(a + b)].count("line") == 2


def test_spinner_breaks_the_run():
    objs = _arc(7, 1.5, 12) + [_o(600, 256, 192, "Spinner")] + _arc(7, 1.5, 12, t0=700, x0=200, y0=300)
    assert len(curves.find(objs, R)) == 2


def test_long_runs_are_chunked_by_beats():
    objs = _arc(40, 1.5, 6)                       # 3.2 s
    whole = curves.find(objs, R)
    cut = curves.find(objs, R, beat_at=lambda t: 500.0)   # 4 beats = 2 s
    assert len(cut) > len(whole)
    assert all(s["t1"] - s["t0"] <= 2000 for s in cut)
