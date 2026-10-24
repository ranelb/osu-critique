"""Annotations: the player's own notes, in map time, and the prompt block."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from osu_critique import annotations

MD5 = "a" * 32
RUN = "b" * 32


def test_add_writes_a_sidecar(tmp_path):
    note = annotations.add(tmp_path, MD5, "the second kiai is the wall")
    path = annotations.sidecar_path(tmp_path, MD5)
    assert path.is_file()
    doc = json.loads(path.read_text())
    assert doc["schema_version"] == annotations.SIDECAR_VERSION
    assert doc["beatmap_md5"] == MD5
    assert doc["notes"][0]["note_id"] == note["note_id"]
    assert doc["notes"][0]["scope"] == "map"
    assert doc["notes"][0]["t_map"] is None
    assert not list(path.parent.glob("*.part"))


def test_run_notes_need_a_replay(tmp_path):
    with pytest.raises(ValueError, match="replay_md5"):
        annotations.add(tmp_path, MD5, "felt sloppy", scope="run")
    note = annotations.add(tmp_path, MD5, "felt sloppy", scope="run", replay_md5=RUN)
    assert note["scope"] == "run" and note["replay_md5"] == RUN
    # a map note never carries a replay id, even if one is passed
    note = annotations.add(tmp_path, MD5, "general", scope="map", replay_md5=RUN)
    assert note["replay_md5"] is None


def test_empty_body_is_refused(tmp_path):
    with pytest.raises(ValueError):
        annotations.add(tmp_path, MD5, "   ")


def test_remove_and_find_owner(tmp_path):
    a = annotations.add(tmp_path, MD5, "one")
    b = annotations.add(tmp_path, "c" * 32, "two")
    assert annotations.find_owner(tmp_path, b["note_id"]) == "c" * 32
    assert annotations.remove(tmp_path, MD5, a["note_id"]) is True
    assert annotations.remove(tmp_path, MD5, a["note_id"]) is False
    assert annotations.find_owner(tmp_path, a["note_id"]) is None


def test_for_map_splits_scopes_and_filters_runs(tmp_path):
    annotations.add(tmp_path, MD5, "map note")
    annotations.add(tmp_path, MD5, "run 1 note", scope="run", replay_md5=RUN)
    annotations.add(tmp_path, MD5, "run 2 note", scope="run", replay_md5="d" * 32)
    only_run = annotations.for_map(tmp_path, MD5, RUN)
    assert [n["body"] for n in only_run["map"]] == ["map note"]
    assert [n["body"] for n in only_run["run"]] == ["run 1 note"]
    both = annotations.for_map(tmp_path, MD5)
    assert len(both["run"]) == 2


def test_notes_are_sorted_by_time_and_labelled(tmp_path):
    annotations.add(tmp_path, MD5, "late", t_map=134.312)
    annotations.add(tmp_path, MD5, "general")
    annotations.add(tmp_path, MD5, "early", t_map=2.5)
    groups = annotations.for_map(tmp_path, MD5)
    assert [n["body"] for n in groups["map"]] == ["early", "late", "general"]
    assert groups["map"][0]["t_label"] == "0:02.500"
    assert groups["map"][1]["t_label"] == "2:14.312"


def test_parse_time_accepts_both_forms_and_rejects_junk():
    assert annotations.parse_time("134.312") == pytest.approx(134.312)
    assert annotations.parse_time("2:14.312") == pytest.approx(134.312)
    assert annotations.parse_time(90) == pytest.approx(90.0)
    assert annotations.parse_time("") is None
    assert annotations.parse_time(None) is None
    with pytest.raises(ValueError):
        annotations.parse_time("two minutes")


def test_fmt_time_is_a_chip():
    assert annotations.fmt_time(134.312) == "2:14.312"
    assert annotations.fmt_time(None) == ""


def test_map_time_survives_a_dt_row_clock():
    # a DT run's rows are in player time: rows_scale = 2/3
    dt = {"rows_scale": 2.0 / 3.0}
    assert annotations.to_map_time(667.0, dt) == pytest.approx(1.0005, abs=1e-3)
    assert annotations.to_row_ms(1.0, dt) == pytest.approx(666.67, abs=1e-2)
    # a normal run is 1:1
    assert annotations.to_map_time(1000.0, {"rows_scale": 1.0}) == pytest.approx(1.0)
    # a legacy artifact with no time_base is treated as 1:1
    assert annotations.to_map_time(1000.0, None) == pytest.approx(1.0)


def test_malformed_sidecar_is_empty_not_fatal(tmp_path):
    path = annotations.sidecar_path(tmp_path, MD5)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert annotations.load(tmp_path, MD5)["notes"] == []
    path.write_text(json.dumps({"notes": [{"scope": "nope", "body": "x"},
                                          {"scope": "map", "body": "ok"}]}))
    notes = annotations.load(tmp_path, MD5)["notes"]
    assert [n["body"] for n in notes] == ["ok"]


def test_a_hand_edited_note_without_an_id_gets_one(tmp_path):
    path = annotations.sidecar_path(tmp_path, MD5)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"notes": [{"scope": "map", "body": "by hand"}]}))
    notes = annotations.load(tmp_path, MD5)["notes"]
    assert notes[0]["note_id"]
    assert notes[0]["body"] == "by hand"


def test_tags_accept_a_string_or_a_list(tmp_path):
    note = annotations.add(tmp_path, MD5, "x", tags="kiai, jumps")
    assert note["tags"] == ["kiai", "jumps"]
    note = annotations.add(tmp_path, MD5, "y", tags=["one"])
    assert note["tags"] == ["one"]


def test_prompt_block_reads_like_instructions(tmp_path):
    annotations.add(tmp_path, MD5, "the second kiai is the wall", t_map=134.312,
                    tags=["kiai"])
    annotations.add(tmp_path, MD5, "felt sloppy", scope="run", replay_md5=RUN)
    notes = annotations.for_metrics({"beatmap_md5": MD5, "replay_md5": RUN}, tmp_path)
    block = annotations.prompt_block(notes)
    assert "player's own notes" in block
    assert "2:14.312" in block
    assert "(map)" in block and "(this play)" in block
    assert "[kiai]" in block
    assert annotations.prompt_block([]) == ""


def test_coach_message_carries_the_notes(tmp_path):
    from osu_critique.coach import build_user_message

    annotations.add(tmp_path, MD5, "this is the hard part", t_map=12.0)
    metrics = {"beatmap_md5": MD5, "replay_md5": RUN, "accuracy": 0.9}
    notes = annotations.for_metrics(metrics, tmp_path)
    message = build_user_message(metrics, notes=notes)
    assert "this is the hard part" in message
    assert "0:12.000" in message
    assert message.index("## Metrics") < message.index("player's own notes")


def test_index_mirrors_the_sidecars(tmp_path):
    from osu_critique import index

    annotations.add(tmp_path, MD5, "mirrored", t_map=3.0)
    stats = index.sweep(tmp_path)
    assert stats["runs"] == 0
    conn = index.connect(tmp_path / index.DB_FILENAME)
    try:
        rows = conn.execute("SELECT note_id, scope, body, t_map FROM annotations").fetchall()
        assert len(rows) == 1
        assert rows[0]["body"] == "mirrored"
        assert rows[0]["t_map"] == pytest.approx(3.0)
        annotations.add(tmp_path, MD5, "second")
        index.sync_annotations(conn, tmp_path)
        assert conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 2
    finally:
        conn.close()
