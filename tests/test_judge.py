"""Judge semantics: presses are consumed in the game's order (osu! semantics),
not matched to whichever object happens to be nearest to them. Plus the whiff
taxonomy (why a press went unused)."""
import numpy as np

from osu_critique.metrics.assignment import (AFTER_END, LOST, MASH, OFF_TARGET,
                                             SLIDER_HEAD, assign_nearest, judge)

W = (25.0, 45.0, 65.0)          # 300/100/50 half-windows (ms), OD ~9
RADIUS = 39.0
SEARCH = 250.0


def _frames(samples):
    """samples: [(t_ms, x, y, keyA_down, keyB_down)]"""
    return [tuple(s) for s in sorted(samples, key=lambda s: s[0])]


def _objs(specs):
    return [{"t": t, "end": t, "x": x, "y": y, "kind": "Circle"} for t, x, y in specs]


def _presses(frames):
    out, prev_a, prev_b = [], False, False
    for t, _x, _y, a, b in frames:
        if a and not prev_a:
            out.append((t, "A"))
        if b and not prev_b:
            out.append((t, "B"))
        prev_a, prev_b = a, b
    return out


def _run(objs, frames, judge_fn):
    times = np.array([f[0] for f in frames])
    presses = _presses(frames)
    return judge_fn(objs, frames, times, presses, [p[0] for p in presses],
                    *W, RADIUS, SEARCH)


def test_press_order_beats_nearest_press():
    """A press already on an object must resolve it, in time order.

    Objects A (t=1000) and B (t=1015) are stacked on the same spot; the player
    clicks at t=960 (late for A, early for B -- the game gives it to A) and
    again at t=1005. Consuming in the game's order: A <- 960 (-40 ms), B <-
    1005 (-10 ms). Nearest-press matching instead hands A the 1005 press (+5)
    and leaves B with -55 ms: a fabricated miss.
    """
    objs = _objs([(1000.0, 100.0, 100.0), (1015.0, 100.0, 100.0)])
    frames = _frames([(0.0, 100.0, 100.0, False, False),
                      (960.0, 100.0, 100.0, True, False),
                      (1005.0, 100.0, 100.0, False, True),
                      (1200.0, 100.0, 100.0, False, False)])

    results, detected, _whiffs = _run(objs, frames, judge)
    assert [round(r["error"]) for r in results] == [-40, -10]
    assert detected["miss"] == 0

    old_results, old_detected, _ = _run(objs, frames, assign_nearest)
    assert [round(r["error"]) for r in old_results] == [5, -55]
    assert old_detected == {"300": 1, "100": 0, "50": 1, "miss": 0}  # B downgraded


def test_cursor_gate_still_applies():
    """A press away from the circle cannot resolve the object."""
    objs = _objs([(1000.0, 100.0, 100.0)])
    frames = _frames([(0.0, 300.0, 300.0, False, False),
                      (1002.0, 300.0, 300.0, True, False),
                      (1100.0, 300.0, 300.0, False, False)])
    results, detected, whiffs = _run(objs, frames, judge)
    assert detected["miss"] == 1
    assert whiffs[OFF_TARGET] == 1 and whiffs["off_target_mean_r"] > 4


def test_whiff_causes_are_separated():
    """mash / off-target / leftover beside a slider / post-map presses differ."""
    objs = _objs([(1000.0, 100.0, 100.0)])
    objs.append({"t": 2000.0, "end": 2400.0, "x": 300.0, "y": 200.0,
                 "kind": "Slider"})
    frames = _frames([
        (0.0, 100.0, 100.0, False, False),
        (500.0, 100.0, 100.0, True, False),    # mash: no object within w50
        (1001.0, 100.0, 100.0, False, False),
        (1400.0, 100.0, 100.0, True, False),   # mash: mid-gap press
        (1999.0, 300.0, 200.0, False, False),
        (2000.0, 300.0, 200.0, True, False),   # takes the slider head
        (2010.0, 300.0, 200.0, False, False),
        (2020.0, 300.0, 200.0, True, False),   # on-target beside the slider head
        (2100.0, 300.0, 200.0, False, False),
        (3200.0, 300.0, 200.0, True, False),   # after the map
        (3300.0, 300.0, 200.0, False, False),
    ])
    _results, _detected, whiffs = _run(objs, frames, judge)
    assert whiffs[MASH] == 2, whiffs
    assert whiffs[SLIDER_HEAD] == 1, whiffs
    assert whiffs[AFTER_END] == 1, whiffs
    assert whiffs["n"] == 4 and whiffs[OFF_TARGET] == 0 and whiffs[LOST] == 0


def test_duplicate_press_on_a_circle_is_lost():
    objs = _objs([(1000.0, 100.0, 100.0)])
    frames = _frames([(0.0, 100.0, 100.0, False, False),
                      (1001.0, 100.0, 100.0, True, False),
                      (1005.0, 100.0, 100.0, False, False),
                      (1010.0, 100.0, 100.0, True, False),
                      (1100.0, 100.0, 100.0, False, False)])
    _results, detected, whiffs = _run(objs, frames, judge)
    assert detected == {"300": 1, "100": 0, "50": 0, "miss": 0}
    assert whiffs[LOST] == 1 and whiffs["n"] == 1
