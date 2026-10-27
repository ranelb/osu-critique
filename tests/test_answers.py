"""Stored answers: canonical files under out/answers/, and the legacy move.

An answer is authored data. The file is the truth; the DB mirrors metadata only.
"""
from __future__ import annotations

import json

from osu_critique import answers, critiques


# ------------------------------------------------------------ scope files ---

def test_answer_sidecars_are_canonical_and_keep_their_summary(tmp_path):
    from osu_critique import answers, critiques

    doc = answers.build(
        digest="d" * 64, text="# Selection summary\n\nhello", selection={"maps": ["a"]},
        system="SYS", model="m", body="the answer", n_runs=3, n_maps=2,
        first="2026-10-01T10:00:00", last="2026-10-02T10:00:00")
    path = answers.save(tmp_path, doc)
    assert path.parts[-2:] == ("answers", "d" * 64 + ".json")
    loaded = answers.load(tmp_path, "d" * 64)
    assert loaded["text"] == "# Selection summary\n\nhello"
    assert loaded["body"] == "the answer"
    assert loaded["selection"] == {"maps": ["a"]}
    assert loaded["prompt_hash"] == critiques.prompt_hash("SYS")


def test_answering_is_newest_first_and_skips_other_files(tmp_path):
    from osu_critique import answers, critiques

    for digest, created in (("a" * 64, "2026-10-01T10:00:00"),
                            ("b" * 64, "2026-10-02T10:00:00")):
        doc = answers.build(
            digest=digest, text="t", selection={}, system="S", model="m",
            body="b", n_runs=1, n_maps=1, first=None, last=None)
        doc["created"] = created
        answers.save(tmp_path, doc)
    (answers.answers_dir(tmp_path) / "junk.json").write_text("{not json")
    rows = answers.all_answers(tmp_path)
    assert [r["hash"] for r in rows] == ["b" * 64, "a" * 64]


def test_removing_an_answer_leaves_the_per_run_ones_alone(tmp_path):
    from osu_critique import answers, critiques

    answers.save(tmp_path, answers.build(
        digest="c" * 64, text="t", selection={}, system="S", model="m",
        body="b", n_runs=1, n_maps=1, first=None, last=None))
    assert answers.remove(tmp_path, "c" * 64) is True
    assert answers.load(tmp_path, "c" * 64) is None
    assert answers.remove(tmp_path, "c" * 64) is False
