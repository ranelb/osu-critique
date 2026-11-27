"""Tempo tags on geometry segments (metrics/rhythm.py)."""
from __future__ import annotations

import math

from osu_critique.metrics import geometry as G
from osu_critique.metrics import rhythm as RH

R = 36.5


def _tri(gap, laps=3, side_r=3.2):
    big = side_r * R / (2 * math.sin(math.pi / 3))
    v = [(256 + big * math.cos(2 * math.pi * j / 3), 192 + big * math.sin(2 * math.pi * j / 3))
         for j in range(3)]
    objs = [{"t": 1000.0 + i * gap, "x": v[i % 3][0], "y": v[i % 3][1], "kind": "Circle"}
            for i in range(3 * laps + 1)]
    for i, o in enumerate(objs):                    # what structure.annotate would give
        o["spacing_r"] = side_r if i else None
    return objs


def _label(gap):
    objs = _tri(gap)
    return RH.tag(objs, G.classify(objs, R))[0]


def test_stream_speed_triangle_is_a_spaced_stream():
    s = _label(100.0)
    assert s["tempo"] == "stream" and s["label"] == "spaced triangle stream"
    assert s["run_share"] >= 0.9      # the first note has no gap, so it is never in a run


def test_slow_triangle_is_jumps():
    s = _label(400.0)                               # slower than any sustained run
    assert s["tempo"] == "jumps" and s["label"] == "triangle jumps"


def test_between_the_two_it_is_a_burst():
    assert _label(200.0)["tempo"] == "burst"


def test_dense_notes_are_named_dense():
    seg = {"shape": "stack", "tempo": "stream", "spacing_r": 0.5}
    assert RH.describe(seg) == "dense stack stream"


def test_empty_is_fine():
    assert RH.tag([], []) == []
