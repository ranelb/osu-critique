"""The per-object record schema: written beside the metrics, frozen, additive."""
import json

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
