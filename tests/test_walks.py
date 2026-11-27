"""One-lap polygons and stars from constant-turn walks on synthetic notes."""
import math

from osu_critique.metrics import walks

R = 40.0


def _o(t, x, y, kind="Circle"):
    return {"t": t, "x": x, "y": y, "kind": kind}


def _walk(n, turn, step_r=3.0, gap=150, h0=0.0, t0=0):
    out, x, y, h = [], 250.0, 200.0, h0
    for i in range(n):
        out.append(_o(t0 + i * gap, x, y))
        x += step_r * R * math.cos(math.radians(h))
        y += step_r * R * math.sin(math.radians(h))
        h += turn
    return out


def _shapes(objs, **kw):
    return [(s["shape"], s["dir"]) for s in walks.find(objs, R, **kw)]


def test_star_one_lap():
    assert _shapes(_walk(6, 144)) == [("star", "cw")]


def test_star_counter_clockwise():
    assert _shapes(_walk(6, -144)) == [("star", "ccw")]


def test_pentagon_one_lap():
    assert _shapes(_walk(6, 72)) == [("pentagon", "cw")]


def test_triangle_and_hexagon():
    assert _shapes(_walk(5, 120))[0][0] == "triangle"
    assert _shapes(_walk(7, 60))[0][0] == "hexagon"


def test_zigzag_is_not_a_walk():
    objs = [_o(i * 150, 150 + (i % 2) * 200, 200 + (i % 2) * 20) for i in range(8)]
    assert walks.find(objs, R) == []


def test_alternating_turn_signs_never_qualify():
    objs, x, y, h = [], 250.0, 200.0, 0.0
    for i in range(8):
        objs.append(_o(i * 150, x, y))
        x += 3 * R * math.cos(math.radians(h)); y += 3 * R * math.sin(math.radians(h))
        h += 144 if i % 2 else -144
    assert walks.find(objs, R) == []


def test_unsteady_tail_is_trimmed():
    objs = _walk(6, 144)
    objs.append(_o(objs[-1]["t"] + 900, objs[-1]["x"] + 20, objs[-1]["y"] + 130))
    segs = walks.find(objs, R)
    assert segs and segs[0]["end"] <= 5


def test_spinner_breaks_the_walk():
    objs = _walk(8, 144)
    objs[4] = _o(objs[4]["t"], objs[4]["x"], objs[4]["y"], "Spinner")
    assert walks.find(objs, R) == []


def test_short_legs_have_no_direction():
    assert walks.find(_walk(8, 144, step_r=1.2), R) == []


def test_beat_cap_trims_long_walks():
    objs = _walk(6, 144, gap=500)
    segs = walks.find(objs, R, beat_at=lambda t: 500.0)    # 5 gaps = 5 beats; trimmed to 4
    assert segs and all(s["t1"] - s["t0"] <= 4 * 500 for s in segs)


def test_repeated_stack_is_not_a_polygon():
    # 4 notes retracing two spots: coincident vertices not one lap apart
    pts = [(200, 200), (320, 200), (200, 200), (320, 200), (200, 200), (320, 200)]
    objs = [_o(i * 150, x, y) for i, (x, y) in enumerate(pts)]
    assert walks.find(objs, R) == []
