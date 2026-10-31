"""Sequence labels: fast groups and repeated turn shapes."""
from __future__ import annotations

import pytest

from osu_critique.metrics import sequences as Q


def row(i, t, *, kind="Circle", result="300", snap=1.0, spacing=3.0,
        x=0.0, y=0.0):
    return {"i": i, "t": float(t), "kind": kind, "result": result,
            "snap": snap, "spacing_r": spacing, "x": float(x), "y": float(y)}


def clip(times, **kw):
    return [row(i, t, **kw) for i, t in enumerate(times)]


def test_group_classes_and_rates():
    # 2 + 3 + 10-note groups, separated by long gaps
    rows = []
    t = 0
    for n in (2, 3, 10):
        for _ in range(n):
            rows.append(row(len(rows), t))
            t += 100
        t += 1000
    block = Q.build(rows)
    classes = {r["class"]: r for r in block["runs"]}
    assert classes["double"]["n"] == 2
    assert classes["triple"]["n"] == 3
    assert classes["stream"]["n"] == 10
    assert classes["stream"]["reported"] is True
    assert classes["stream"]["gap_ms_median"] == pytest.approx(100.0)


def test_a_long_half_time_run_is_sustained_not_a_deathstream():
    # 40 notes at 156 ms with 1/2 snap: steady, but not stream density
    rows = [row(i, i * 156, snap=2.0) for i in range(40)]
    block = Q.build(rows)
    classes = {r["class"]: r for r in block["runs"]}
    assert "deathstream" not in classes
    assert classes["sustained"]["n"] == 40


def test_a_long_quarter_note_run_is_a_deathstream():
    rows = [row(i, i * 80, snap=1.0) for i in range(40)]
    block = Q.build(rows)
    assert {r["class"] for r in block["runs"] if r["reported"]} == {"deathstream"}


def test_small_buckets_are_not_reported():
    rows = clip([0, 100])                         # one double, below the gate
    block = Q.build(rows)
    assert block["runs"][0]["reported"] is False


def test_square_turns_are_labelled():
    pts = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
    rows = [row(i, i * 100, spacing=3.0, x=x, y=y)
            for i, (x, y) in enumerate(pts)]
    turns = Q._turns(rows)
    assert Q.shape_label(rows, 4, turns) == "square"


def test_a_straight_line_is_not_a_shape():
    rows = [row(i, i * 100, spacing=3.0, x=i * 100.0, y=0.0) for i in range(6)]
    turns = Q._turns(rows)
    assert Q.shape_label(rows, 4, turns) is None


def test_standout_is_a_contrast_not_an_absolute_rate():
    overall = 0.20
    bad = Q._class_row("double", [row(i, i * 100, result="miss") for i in range(10)],
                       gate_n=8, overall=overall)
    ok = Q._class_row("triple", [row(i, i * 100) for i in range(10)],
                      gate_n=8, overall=overall)
    assert bad["standout"] is True and bad["contrast"] > 1.5
    assert ok["standout"] is True and ok["contrast"] < 0.6
    # same rate, small bucket: not evidence
    small = Q._class_row("burst", [row(i, i * 100, result="miss") for i in range(3)],
                         gate_n=8, overall=overall)
    assert small["reported"] is False and small["standout"] is False
