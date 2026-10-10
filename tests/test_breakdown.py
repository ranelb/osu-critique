"""The breakdown block: how a play fails, recomputed from raw geometry.

The point of recomputing the required cursor speed here (rather than reading
``objects[].cursor_speed``) is that the latter is null on no-press misses, so a
naive bin hides exactly the misses that matter. These tests plant a known speed
ramp and a miss in it and check the miss lands in the right bin.
"""
from __future__ import annotations

import pytest

from osu_critique.metrics import breakdown as B


def ramp_objects(speeds, dt=100.0, start=1000.0, y=0.0):
    """Objects whose required speed (dist/dt) is exactly ``speeds`` in order.

    Object 0 is the origin (no predecessor, no required speed). Each later
    object is placed so the travel from its predecessor needs ``v`` px/ms.
    """
    objs = [{"i": 0, "x": 0.0, "y": y, "t": start, "result": "300",
             "angle_deg": None, "spacing_r": None, "aim_r": 0.3}]
    x = 0.0
    for i, v in enumerate(speeds, start=1):
        dx = v * dt
        x += dx
        objs.append({"i": i, "x": x, "y": y, "t": start + i * dt,
                     "result": "300", "angle_deg": 0.0,
                     "spacing_r": None, "aim_r": 0.3})
    return objs


def test_required_speed_is_recomputed_from_geometry():
    objs = ramp_objects([0.25, 0.75, 1.25])
    req = B.required_speeds(objs)
    assert req[1] == pytest.approx(0.25)
    assert req[2] == pytest.approx(0.75)
    assert req[3] == pytest.approx(1.25)
    assert 0 not in req                      # the first object has no travel


def test_a_long_break_is_not_travel():
    objs = ramp_objects([1.0, 1.0])
    objs[2]["t"] = objs[1]["t"] + 5000.0     # a 5 s pause, not a jump
    assert 2 not in B.required_speeds(objs)


def test_a_null_cursor_speed_miss_still_lands_in_its_bin():
    """The regression the block exists for: a no-press miss has no
    cursor_speed, so binning on that field would hide it. It must show in the
    bin its *geometry* requires."""
    objs = ramp_objects([1.2] * 12 + [2.2] * 12)
    for i in (18, 20, 22, 24):               # misses only in the fast stretch
        objs[i]["result"] = "miss"
    for o in objs:                           # emulate the real records: null
        o["cursor_speed"] = None

    block = B.build(objs)
    fast = next(r for r in block["speed_bins"] if r["lo"] == 2.0)
    slow = next(r for r in block["speed_bins"] if r["lo"] == 1.0)
    assert fast["miss"] == 4 and fast["rate"] > 0
    assert slow["miss"] == 0
    assert block["cliff"] == pytest.approx(2.0)
    assert block["knee"] == pytest.approx(1.5)


def test_bins_gate_the_cliff_like_the_skill_does():
    # fewer than min_blow in the bad bin: not a cliff yet, however bad the rate
    rows = [{"label": "3-4", "lo": 3.0, "hi": 4.0, "n": 2, "miss": 2, "rate": 100.0},
            {"label": "2-2.5", "lo": 2.0, "hi": 2.5, "n": 3, "miss": 3, "rate": 100.0},
            {"label": "1-1.5", "lo": 1.0, "hi": 1.5, "n": 50, "miss": 1, "rate": 2.0}]
    assert B.cliff_knee(rows) == (1.5, None)


def test_cascades_are_consecutive_runs_not_isolated_whiffs():
    objs = ramp_objects([1.0] * 10)
    for i in (3, 4, 5):                      # a 3-run
        objs[i]["result"] = "miss"
    objs[10]["result"] = "miss"              # an isolated whiff
    for i in (6, 7):
        objs[i]["result"] = "miss"           # extends to 3..7 -> a 5-run
    c = B.cascades(objs)
    assert c[0]["n"] == 5 and c[0]["start_i"] == 3 and c[0]["end_i"] == 7
    assert all(r["n"] >= 2 for r in c)       # the isolated miss is not a cascade


def test_build_ramp_reports_the_missiest_window():
    objs = ramp_objects([1.0] * 40)
    for i in range(20, 24):
        objs[i]["result"] = "miss"
    block = B.build(objs)
    ramp = block["ramp"]
    assert ramp["miss"] >= 4
    assert any(20 <= i <= 23 for i in ramp["object_ids"])
    assert ramp["t0"] <= ramp["t1"] and ramp["speed"] is not None
