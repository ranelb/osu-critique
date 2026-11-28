"""Spinners are rated by spin completion, not through the circle OD windows."""
import math

import numpy as np

from osu_critique.metrics import spinner as sp
from osu_critique.metrics.assignment import judge

OD = 8.0


def _frames(t0, t1, turns, step=8.0, held=True):
    """Cursor circling the centre ``turns`` times over [t0, t1]."""
    out = []
    n = int((t1 - t0) / step)
    for k in range(n + 1):
        a = 2 * math.pi * turns * k / n
        out.append((t0 + k * step, 256 + 100 * math.cos(a), 192 + 100 * math.sin(a),
                    held, False))
    return out


def _obj(t, end, kind="Spinner", x=256, y=192):
    return {"t": float(t), "end": float(end), "kind": kind, "x": x, "y": y}


def _run(objs, frames, scale=1.0, presses=()):
    times = np.array([f[0] for f in frames])
    pr = [(p, "A") for p in presses]
    return judge(objs, frames, times, pr, [p for p, _ in pr], 30, 70, 110, 30, 250,
                 spinner_od=OD, scale=scale)


def test_spins_required_follows_od_and_duration():
    assert sp.spins_required(5.0, 2000) == 5            # 2.5 spins/s at OD5
    assert sp.spins_required(10.0, 2000) == 7           # 3.75 spins/s
    assert sp.spins_required(0.0, 2000) == 3            # 1.5 spins/s
    assert sp.spins_required(OD, 100) == 0


def test_rotations_counts_turns_and_ignores_direction():
    f = _frames(0, 1000, 4)
    t = [x[0] for x in f]
    assert abs(sp.rotations(f, t, 0, 1000) - 4.0) < 0.05
    back = [(x[0], x[1], 384 - x[2], x[3], x[4]) for x in f]     # mirrored: other way round
    assert abs(sp.rotations(back, t, 0, 1000) - 4.0) < 0.05


def test_rate_thresholds():
    assert [sp.rate(p) for p in (1.0, 0.95, 0.8, 0.5)] == ["300", "100", "50", "miss"]


def test_completed_spinner_is_300_whatever_the_presses_did():
    # 2 s at OD8 needs int(2 * 3.25) = 6 turns; the player turns 9 and never taps
    f = _frames(1000, 3000, 9)
    res, det, whiffs = _run([_obj(1000, 3000)], f)
    assert res[0]["result"] == "300"
    assert res[0]["error"] is None and res[0]["aim"] is None
    assert res[0]["spin_required"] == 6 and res[0]["spin_progress"] > 1.0
    assert det == {"300": 1, "100": 0, "50": 0, "miss": 0}


def test_barely_spun_spinner_is_a_miss_even_with_a_perfectly_timed_press():
    f = _frames(1000, 3000, 1)
    res, det, _ = _run([_obj(1000, 3000)], f, presses=[1000.0])
    assert res[0]["result"] == "miss"
    assert res[0]["spin_progress"] < 0.75
    assert det["miss"] == 1


def test_partial_spin_gets_the_intermediate_ratings():
    f = _frames(1000, 3000, 5.5)                  # 5.5 / 6 = 0.92 -> 100
    assert _run([_obj(1000, 3000)], f)[0][0]["result"] == "100"
    f = _frames(1000, 3000, 4.8)                  # 0.8 -> 50
    assert _run([_obj(1000, 3000)], f)[0][0]["result"] == "50"


def test_dt_requirement_uses_map_time():
    # real-time duration 1333 ms is 2000 ms of map time at scale 2/3: still 6 turns
    f = _frames(1000, 1000 + 1333, 7)
    res, _, _ = _run([_obj(1000, 1000 + 1333)], f, scale=2 / 3)
    assert res[0]["spin_required"] == 6 and res[0]["result"] == "300"


def test_spinner_takes_no_press_and_presses_inside_are_not_whiffs():
    f = _frames(0, 4000, 24, held=False)
    objs = [_obj(500, 2500), _obj(3000, 3000, kind="Circle", x=256 + 100, y=192)]
    # a tap mid-spin and an on-time tap on the circle (cursor sits near x=356)
    t_circle = min(f, key=lambda x: abs(x[0] - 3000))
    objs[1]["x"], objs[1]["y"] = t_circle[1], t_circle[2]
    res, det, whiffs = _run(objs, f, presses=[1500.0, 3000.0])
    assert [x["result"] for x in res] == ["300", "300"]
    assert whiffs["n"] == 0                       # the mid-spin tap is spinning, not a whiff
    assert res[1]["press_t"] == 3000.0


def test_without_od_a_spinner_is_300_not_timed():
    f = _frames(0, 2000, 0.2)
    times = np.array([x[0] for x in f])
    res, det, _ = judge([_obj(0, 2000)], f, times, [(900.0, "A")], [900.0],
                        30, 70, 110, 30, 250)
    assert res[0]["result"] == "300" and res[0]["spin_progress"] is None
