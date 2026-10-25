"""The run-page boards: near-miss ranking, chains, and the clean-stretch fallback."""
from __future__ import annotations

from osu_critique.web import boards


def objects(n=10):
    return [{"i": i, "x": 100 + i * 40, "y": 100 + (i % 3) * 50,
             "kind": "Circle" if i % 2 else "Slider", "result": "300"}
            for i in range(n)]


def miss(i, closest, turn=120.0, press=-10.0):
    return {"i": i, "t": 1000.0 * i, "kind": "Circle", "d_r": 1.0,
            "closest_r": closest, "aim_at_press_r": 1.2, "press_ms": press,
            "key": "A", "gap_r": 5.0, "turn_deg": turn, "speed": 0.4}


def metrics(misses, streams=None, quarters=None):
    return {"autopsy": {"misses": {"rows": misses}},
            "streams": {"segments": streams or []},
            "quarters": quarters or [],
            "spacing_radius": 40.0}


def test_near_misses_are_ranked_by_closest_approach():
    m = metrics([miss(2, 1.4), miss(5, 0.2), miss(7, 0.9)])
    built = boards.build(m, objects())
    assert [b["i"] for b in built["misses"]] == [5, 7, 2]
    assert built["misses"][0]["closest_r"] == 0.2


def test_each_board_carries_a_five_note_window():
    built = boards.build(metrics([miss(5, 0.3)]), objects())
    chain = built["misses"][0]["chain"]
    assert [c["i"] for c in chain] == [3, 4, 5, 6, 7]
    miss_obj = next(c for c in chain if c["i"] == 5)
    assert built["misses"][0]["chain"].count(miss_obj) == 1


def test_a_window_at_the_edge_is_clipped_not_dropped():
    built = boards.build(metrics([miss(0, 0.3)]), objects())
    assert [c["i"] for c in built["misses"][0]["chain"]] == [0, 1, 2]


def test_coordinates_are_clamped_to_the_playfield():
    objs = objects()
    objs[4] = dict(objs[4], x=-50, y=900)
    built = boards.build(metrics([miss(4, 0.3)]), objs)
    node = next(c for c in built["misses"][0]["chain"] if c["i"] == 4)
    assert node["x"] == 0 and node["y"] == 384


def test_heat_is_every_miss_with_a_position():
    built = boards.build(metrics([miss(2, 0.4), miss(9, 0.6)]), objects())
    assert len(built["heat"]) == 2
    assert {"x", "y", "closest_r"} <= set(built["heat"][0])


def test_clean_streams_win_when_there_are_enough_notes():
    streams = [{"t_start": 0, "t_end": 5000, "n": 20, "miss": 0,
                "notes_per_s": 8.0, "gap_ms": 120, "alt_ratio": 1.0},
               {"t_start": 0, "t_end": 2000, "n": 9, "miss": 2,
                "notes_per_s": 9.0, "gap_ms": 110, "alt_ratio": 1.0}]
    good = boards.build(metrics([], streams=streams), objects())["good"]
    assert len(good) == 1 and good[0]["kind"] == "stream"
    assert good[0]["n"] == 20


def test_short_maps_fall_back_to_clean_quarters():
    quarters = [{"range": [1000.0, 9000.0], "n": 54, "miss": 0,
                 "mean_err": 5.9, "std_err": 12.2},
                {"range": [9000.0, 18000.0], "n": 40, "miss": 1,
                 "mean_err": 3.0, "std_err": 9.0}]
    good = boards.build(metrics([], quarters=quarters), objects())["good"]
    assert len(good) == 1
    assert good[0]["kind"] == "quarter" and good[0]["n"] == 54
    assert good[0]["t_start"] == 1000.0


def test_nothing_to_show_is_an_empty_but_valid_block():
    built = boards.build(metrics([]), objects())
    assert built["misses"] == [] and built["heat"] == [] and built["good"] == []
    assert built["radius"] == 40.0
