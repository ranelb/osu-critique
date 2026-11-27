"""The per-object record schema: written beside the metrics, frozen, additive."""
import json

import pytest

from osu_critique.cli import main
from osu_critique.metrics.structure import OBJECT_FIELDS, SCHEMA_VERSION
from osu_critique.report import analyze

MAP = "tests/fixtures/aaaaa.osu"
REPLAY = "tests/fixtures/aaaaa.osr"


def _run(tmp_path, tag="aaaaa", **kw):
    metrics = analyze(REPLAY, MAP, tag=tag, outdir=str(tmp_path), console=False, **kw)
    return metrics, tmp_path / f"{tag}_objects.json"


def test_records_match_the_documented_schema(tmp_path):
    metrics, path = _run(tmp_path)
    doc = json.loads(path.read_text())
    assert doc["schema_version"] == SCHEMA_VERSION
    assert len(doc["beatmap_md5"]) == 32
    assert doc["trust"]["judged"] > 0
    assert len(doc["objects"]) == metrics["n_objects"] == metrics["n_objects_map"]
    for rec in doc["objects"]:
        assert tuple(rec.keys()) == OBJECT_FIELDS
        assert rec["result"] in ("300", "100", "50", "miss")
        assert rec["kind"] in ("Circle", "Slider", "Spinner")
        assert isinstance(rec["t"], float) and rec["t"] >= 0
    # the first object has no predecessor; the second has no turn yet
    assert doc["objects"][0]["spacing_r"] is None
    assert doc["objects"][0]["angle_deg"] is None
    assert doc["objects"][1]["angle_deg"] is None
    assert all(r["spacing_r"] is not None for r in doc["objects"][1:])


def test_records_are_json_safe(tmp_path):
    """allow_nan=False in the writer: a NaN or inf would have raised already."""
    _metrics, path = _run(tmp_path)
    text = path.read_text()
    assert "NaN" not in text and "Infinity" not in text
    json.loads(text)


def test_structure_fields_are_sane(tmp_path):
    _metrics, path = _run(tmp_path)
    objects = json.loads(path.read_text())["objects"]

    snaps = [r["snap"] for r in objects if r["snap"] is not None]
    assert all(s > 0 for s in snaps)
    if snaps:                      # the fixture has uninherited timing points
        common = (1, 2, 3, 4, 6, 8, 12, 16)
        hits = sum(1 for s in snaps if any(abs(s - c) < 0.25 for c in common))
        assert hits / len(snaps) > 0.5, "snap should land on note divisors"

    angles = [r["angle_deg"] for r in objects if r["angle_deg"] is not None]
    assert angles and all(0.0 <= a <= 180.0 for a in angles)

    strains = [r for r in objects[1:] if r["strain_aim"] is not None]
    assert len(strains) > 0.8 * (len(objects) - 1)      # slider 0.8.4 supports this
    assert all(r["strain_aim"] >= 0 and r["strain_speed"] >= 0 for r in strains)


def test_no_objects_flag_skips_the_file(tmp_path):
    rc = main(["analyze", REPLAY, MAP, "noobj", "--no-objects",
               "--outdir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "noobj_metrics.json").exists()
    assert not (tmp_path / "noobj_objects.json").exists()


def test_slider_context_and_tail_aware_spacing(tmp_path):
    metrics, path = _run(tmp_path)
    doc = json.loads(path.read_text())
    radius = metrics["spacing_radius"]

    sliders = [r for r in doc["objects"] if r["kind"] == "Slider"]
    assert sliders, "the fixture has a slider"
    for rec in sliders:
        assert rec["sv"] > 0
        assert isinstance(rec["kiai"], bool)
        assert rec["curve_type"] in ("Linear", "Perfect", "MultiBezier", "Catmull")
        assert rec["slider_path_px"] is not None and rec["slider_path_px"] > 0
        assert rec["repeats"] >= 1
        assert rec["slider_tail_x"] is not None and rec["slider_tail_y"] is not None
    assert all(isinstance(r["stack"], bool) for r in doc["objects"])

    # tail-aware spacing is a pure function of the rows; the fixture's only
    # slider is last, so pin it on a synthetic pair
    from osu_critique.metrics.patterns import add_pattern_labels
    rows = [{"x": 0.0, "y": 0.0, "end_x": 100.0, "end_y": 0.0},
            {"x": 0.0, "y": 0.0}]
    add_pattern_labels(rows, radius=10.0)
    assert rows[1]["spacing_r"] == pytest.approx(10.0)   # 100 px from the tail


def test_the_metrics_carry_the_lazer_ground_truth(tmp_path):
    metrics, _path = _run(tmp_path)
    assert metrics["score_meta"]["online_id"] == 6931937233
    assert metrics["score_meta"]["source"].startswith("lazer")
    truth = metrics["slider_truth"]
    assert truth["tail_total"] == 1          # aaaaa has one slider
    assert truth["tail_missed"] is not None
    assert "sequences" in metrics and "runs" in metrics["sequences"]
    assert metrics["trust"]["rate_source"] in ("lazer score info", "legacy mod flag")


def test_pattern_class_fields_are_present_and_in_vocabulary(tmp_path):
    from osu_critique.metrics import legs
    _metrics, path = _run(tmp_path)
    doc = json.loads(path.read_text())
    assert doc["schema_version"] == SCHEMA_VERSION == 3
    objects = doc["objects"]
    assert objects[0]["leg_dist"] is None and objects[0]["leg_flow"] is None
    for rec in objects:
        assert rec["leg_dist"] in (None, *legs.DIST)
        assert rec["leg_flow"] in (None, *legs.FLOW)
        assert rec["leg_tempo"] in (None, *legs.TEMPO)
        assert (rec["leg_dist"] is None) == (rec["leg_tempo"] is None)
    # every leg between two non-spinner objects has a descriptor: nothing is skipped
    for prev, rec in zip(objects, objects[1:]):
        if "Spinner" not in (prev["kind"], rec["kind"]):
            assert rec["leg_dist"] is not None


def test_pattern_classes_are_deterministic(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _m, a = _run(tmp_path / "a")
    _m, b = _run(tmp_path / "b")
    fields = ("shape", "walk", "curve", "leg_dist", "leg_flow", "leg_tempo")
    pick = lambda p: [[r[f] for f in fields] for r in json.loads(p.read_text())["objects"]]
    assert pick(a) == pick(b)


def test_classes_follow_the_played_clock(tmp_path):
    """DT squeezes the gaps: the same map reads faster, never slower, than at NM."""
    order = {"slow": 0, "mid": 1, "fast": 2}
    nm = analyze("tests/fixtures/synth_clean.osr", "tests/fixtures/synth_clean.osu", tag="nm",
                 outdir=str(tmp_path), console=False)
    dt = analyze("tests/fixtures/synth_dt.osr", "tests/fixtures/synth_clean.osu", tag="dt",
                 outdir=str(tmp_path), console=False)
    a = json.loads((tmp_path / "nm_objects.json").read_text())["objects"]
    b = json.loads((tmp_path / "dt_objects.json").read_text())["objects"]
    assert nm["n_objects"] == dt["n_objects"]
    assert any(r["leg_tempo"] for r in b)
    for x, y in zip(a, b):
        if x["leg_tempo"] and y["leg_tempo"]:
            assert order[y["leg_tempo"]] >= order[x["leg_tempo"]]


def test_analyze_writes_the_class_miss_block_and_section_strains(tmp_path):
    pytest.importorskip("rosu_pp_py")
    metrics, path = _run(tmp_path, tag="cm")
    block = metrics["class_miss"]
    assert block["available"] and block["n_population"] > 0
    for c in block["classes"]:
        assert c["n"] >= max(10, block["min_n"])   # never a rate from n < 10
    recs = json.loads(path.read_text())["objects"]
    assert all(r["sec_aim"] is not None for r in recs[1:])
