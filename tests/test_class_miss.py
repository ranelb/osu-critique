"""Per-class miss rates: gates, intervals, matched contrasts, map-clustered pooling.

Fixture: ``tests/fixtures/class_miss/maps.json`` (``scripts/make_class_miss_fixtures.py``),
a planted structure: ``walk:star`` costs +10 pp for real, ``dist:wide`` only looks hard
because it sits in high-strain sections, ``walk:hexagon`` is neutral, ``curve:arc`` is
four objects (below the gate).
"""
import json
from pathlib import Path

import pytest

from osu_critique.metrics import class_miss

FIX = Path(__file__).parent / "fixtures" / "class_miss" / "maps.json"


@pytest.fixture(scope="module")
def maps():
    doc = json.loads(FIX.read_text())
    cols = doc["columns"]
    return {m: [dict(zip(cols, r)) for r in rows] for m, rows in doc["maps"].items()}


def test_wilson_is_bounded_and_widens_with_small_n():
    assert class_miss.wilson(0, 0) == (0.0, 0.0)
    lo, hi = class_miss.wilson(0, 20)
    assert lo == 0.0 and 0.1 < hi < 0.2
    assert class_miss.wilson(5, 1000)[1] - class_miss.wilson(5, 1000)[0] < \
        class_miss.wilson(1, 200)[1] - class_miss.wilson(1, 200)[0]
    assert class_miss.wilson(10, 10)[1] == 1.0


def test_gate_never_below_ten_and_scales_with_map_size():
    assert class_miss.min_n(100) == 10        # 3 % -> 8, floored at 10
    assert class_miss.min_n(500) == 15
    assert class_miss.min_n(5000) == 20


def test_small_classes_are_held_back_not_reported(maps):
    rows = maps["map00"]
    block = class_miss.build(rows)
    names = {c["class"] for c in block["classes"]}
    assert "curve:arc" not in names           # 4 objects
    assert block["held_back"] >= 1
    for c in block["classes"]:
        assert c["n"] >= max(10, block["min_n"])
        assert 0.0 <= c["ci"][0] <= c["rate"] <= c["ci"][1] <= 1.0


def test_relax_is_unavailable_not_zero():
    block = class_miss.build([], unavailable="Relax")
    assert block == {"available": False, "reason": "Relax"}


def test_spinners_are_not_population(maps):
    rows = [dict(r) for r in maps["map00"]]
    rows += [{"kind": "Spinner", "result": "miss", "leg_dist": "wide"}] * 50
    assert class_miss.build(rows)["n_population"] == len(maps["map00"])


def test_build_is_deterministic(maps):
    a = class_miss.build(maps["map03"], 150)
    b = class_miss.build(maps["map03"], 150)
    assert json.dumps(a) == json.dumps(b)


def test_strain_control_removes_the_confounder(maps):
    pooled = class_miss.pool(maps, boot=200)
    by = {c["class"]: c for c in pooled["classes"]}
    wide, star, hexa = by["dist:wide"], by["walk:star"], by["walk:hexagon"]
    assert wide["vs_rest"] > 0.04                       # looks hard...
    assert abs(wide["adj_strain"]) < 0.03               # ...because the strain is high
    assert star["adj_strain"] == pytest.approx(0.10, abs=0.025)
    lo, hi = star["adj_strain_ci"]
    assert lo > 0.03 and hi < 0.16
    lo, hi = hexa["adj_strain_ci"]
    assert lo < 0 < hi                                  # no effect: the interval spans 0
    assert "curve:arc" not in by                        # one map, four objects


def test_pool_is_deterministic_and_clustered_by_map(maps):
    a = class_miss.pool(maps, boot=100)
    assert json.dumps(a) == json.dumps(class_miss.pool(maps, boot=100))
    # a second run of the same map is the same cluster: n doubles, the interval must not
    # shrink the way a naive per-object interval would
    doubled = {m: rows + rows for m, rows in maps.items()}
    star1 = {c["class"]: c for c in a["classes"]}["walk:star"]
    star2 = {c["class"]: c for c in class_miss.pool(doubled, boot=100)["classes"]}["walk:star"]
    w1 = star1["adj_strain_ci"][1] - star1["adj_strain_ci"][0]
    w2 = star2["adj_strain_ci"][1] - star2["adj_strain_ci"][0]
    assert star2["n"] == 2 * star1["n"]
    assert w2 > 0.8 * w1                                # copies are not new evidence


def test_matched_contrast_needs_a_comparison_group():
    cls = {"a": (3, 10)}
    assert class_miss.matched(cls, {"a": (3, 10)}) == (None, 0)     # nothing to compare to
    val, used = class_miss.matched(cls, {"a": (4, 30)})
    assert used == 10 and val == pytest.approx(0.3 - 1 / 20)


def test_section_strains_start_at_the_first_object_section():
    from osu_critique.metrics.difficulty import attach_section_strains
    strains = {"length": 400.0, "aim": [1.0, 2.0, 3.0], "speed": [4.0, 5.0, 6.0]}
    rows = [{"t": 126100.0}, {"t": 126500.0}, {"t": 127300.0}, {"t": 129000.0}]
    attach_section_strains(rows, strains)
    assert [r["sec_aim"] for r in rows] == [1.0, 2.0, 3.0, None]
