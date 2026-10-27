"""The scope builder: resolve a selection, render the text, never guess.

The text is the whole contract with the model, so these tests are about what it
says and what it leaves out — not only about it not crashing.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from osu_critique import index, scope

MAP_A = "a" * 32
MAP_B = "b" * 32


def metrics_doc(tag, replay, beatmap, accuracy, played_at, mods="NM", miss=1,
                ur=180.0, mean=1.0, std=18.0, trustworthy=True, n=100):
    return {
        "schema_version": 1, "tag": tag, "beatmap_md5": beatmap,
        "replay_md5": replay, "played_at": played_at, "player": "test",
        "map": f"Artist - Map {beatmap[:2].upper()} [Insane]",
        "mods": {"DT": mods == "DT", "RX": False, "AP": False},
        "mod_string": mods, "time_scale": 1.0,
        "difficulty": {"CS": 4.0, "AR": 9.0, "OD": 8.0, "HP": 5.0},
        "n_objects": n, "n_objects_map": n,
        "accuracy": accuracy, "max_combo": 80, "full_combo": False,
        "ur": ur, "ur_pct_of_300_window": 50.0,
        "hit_error_ms": {"mean": mean, "std": std, "p10": -20.0, "p90": 20.0,
                         "abs_mean": 15.0},
        "aim_px": {"mean": 12.0, "p90": 20.0, "mean_norm": 0.4},
        "whiffed_presses": 2,
        "counts_recorded": {"300": n - miss - 5, "100": 5, "50": 0, "miss": miss},
        "counts_detected": {"300": n - miss - 5, "100": 5, "50": 0, "miss": miss},
        "trust": {"trustworthy": trustworthy, "abs_delta_total": 0,
                  "abs_delta_pct": 0.0, "judged": n,
                  "count_deltas": {"300": 0, "100": 0, "50": 0, "miss": 0}},
        "failed_play": False,
        "time_base": {"overridden": False, "note": None},
        "windows_ms": {"300": 24.8, "100": 66.4, "50": 108.0},
        "profile": {"composition": [], "rate": {}, "sliders": {}},
        "autopsy": {"shapes": {"classes": []}, "misses": {"rows": []}},
        "aim_mode": {"is_relax": False, "mean_norm": 0.4},
        "streams": {"segments": []},
        "quarters": [],
    }


@pytest.fixture
def corpus(tmp_path):
    """Three runs: two on map A (one untrusted), one on map B."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "beatmap_status.json").write_text(json.dumps({}))
    (out / "stars_by_md5.json").write_text(json.dumps({MAP_A: {"NM": 6.4}}))
    docs = [
        metrics_doc("a1", "1" * 32, MAP_A, 0.80, "2026-10-01T10:00:00"),
        metrics_doc("a2", "2" * 32, MAP_A, 0.95, "2026-10-02T10:00:00",
                    mods="DT"),
        metrics_doc("b1", "3" * 32, MAP_B, 0.70, "2026-10-20T10:00:00",
                    trustworthy=False),
    ]
    for doc in docs:
        path = out / f"{doc['tag']}_metrics.json"
        path.write_text(json.dumps(doc))
        index.upsert_run(doc, path, outdir=out)
    conn = index.connect(out / index.DB_FILENAME)
    yield out, conn
    conn.close()


def run_ids(rows):
    return [r["tag"] for r in rows]


# ---------------------------------------------------------------- resolve ---

def test_selectors_union_and_dedupe(corpus):
    out, conn = corpus
    selection = {"runs": ["1" * 32], "maps": [MAP_A], "since": None, "until": None}
    rows = scope.resolve(conn, selection)
    # a1 is named twice: by replay and by its map; it must appear once
    assert run_ids(rows) == ["a1", "a2"]
    assert len({r["run_id"] for r in rows}) == len(rows)


def test_rows_are_ordered_by_play_time(corpus):
    _out, conn = corpus
    rows = scope.resolve(conn, {"maps": [MAP_A, MAP_B], "runs": [],
                                "since": None, "until": None})
    assert run_ids(rows) == ["a1", "a2", "b1"]


def test_a_range_reads_played_at_not_indexed_at(corpus):
    _out, conn = corpus
    rows = scope.resolve(conn, {"runs": [], "maps": [],
                                "since": "2026-10-02", "until": "2026-10-02"})
    assert run_ids(rows) == ["a2"]          # the whole day, inclusive


def test_an_unknown_selector_is_empty_not_an_error(corpus):
    _out, conn = corpus
    assert scope.resolve(conn, {"runs": ["nope"], "maps": [], "since": None,
                                "until": None}) == []
    # a run id is the replay md5, not the tag: the tag is a filename fragment
    assert scope.resolve(conn, {"runs": ["a1"], "maps": [], "since": None,
                                "until": None}) == []


def test_from_query_tolerates_junk():
    selection = scope.from_query({"runs": " a1 ,, a1 ,b2", "maps": "",
                                  "since": " 7d ", "until": None})
    assert selection["runs"] == ["a1", "b2"]
    assert selection["maps"] == []
    assert selection["since"] == "7d"


def test_a_mod_filter_narrows_maps_and_ranges_but_not_chosen_replays(corpus):
    out, conn = corpus
    # a2 is the DT attempt on map A; a1 is NM
    rows = scope.resolve(conn, {"maps": [MAP_A], "runs": [], "since": None,
                                "until": None, "mods": "NM"})
    assert run_ids(rows) == ["a1"]
    rows = scope.resolve(conn, {"maps": [MAP_A], "runs": [], "since": None,
                                "until": None, "mods": "DT"})
    assert run_ids(rows) == ["a2"]
    # a replay you named is included whatever the filter says
    rows = scope.resolve(conn, {"maps": [], "runs": ["1" * 32], "since": None,
                                "until": None, "mods": "DT"})
    assert run_ids(rows) == ["a1"]


def test_the_mod_filter_is_stated_in_the_text(corpus):
    out, conn = corpus
    built = scope.build(conn, out, {"runs": [], "maps": [MAP_A], "since": None,
                                    "until": None, "mods": "NM"}, system="SYS")
    assert "only NM plays" in built["text"]


# ----------------------------------------------------------------- render ---

def test_small_selection_includes_the_per_replay_reports(corpus):
    out, conn = corpus
    built = scope.build(conn, out, {"runs": [], "maps": [MAP_A], "since": None,
                                    "until": None}, system="SYS")
    text = built["text"]
    assert built["n_runs"] == 2
    assert "## Per-replay reports" in text
    assert "## Map profile" in text                # from report_sections
    assert "nothing was omitted" in text
    assert "2 chosen replay(s)" not in text        # selected by map, not replay
    assert "1 map(s), every attempt" in text


def test_large_selection_drops_the_reports_and_says_so(corpus, monkeypatch):
    out, conn = corpus
    monkeypatch.setattr(scope, "FULL_REPORT_LIMIT", 1)
    built = scope.build(conn, out, {"runs": [], "maps": [MAP_A, MAP_B],
                                    "since": None, "until": None}, system="SYS")
    text = built["text"]
    assert "## Per-replay reports" not in text
    assert "per-replay reports (the selection is above 1 runs)" in text
    assert "## Maps, busiest first" in text        # the aggregate stays


def test_the_header_counts_what_the_map_table_capped(corpus, monkeypatch):
    out, conn = corpus
    monkeypatch.setattr(scope, "MAP_TABLE_LIMIT", 1)
    built = scope.build(conn, out, {"runs": [], "maps": [MAP_A, MAP_B],
                                    "since": None, "until": None}, system="SYS")
    assert "1 further maps with fewer plays are not listed" in built["text"]


def test_the_stability_block_appears_for_repeated_maps(corpus):
    out, conn = corpus
    built = scope.build(conn, out, {"runs": [], "maps": [MAP_A, MAP_B],
                                    "since": None, "until": None}, system="SYS")
    assert "## Stability across attempts" in built["text"]
    assert "CROSS-ATTEMPT" in built["text"]


def test_notes_are_inside_the_text_not_appended_later(corpus):
    from osu_critique import annotations

    out, conn = corpus
    annotations.add(out, MAP_A, body="the second kiai is where I lose it",
                    scope="map")
    built = scope.build(conn, out, {"runs": [], "maps": [MAP_A], "since": None,
                                    "until": None}, system="SYS")
    assert "## The player's own notes" in built["text"]
    assert "the second kiai is where I lose it" in built["text"]


def test_an_empty_selection_says_nothing_matched(corpus):
    out, conn = corpus
    built = scope.build(conn, out, {"runs": ["nope"], "maps": [], "since": None,
                                    "until": None}, system="SYS")
    assert built["n_runs"] == 0
    assert "Nothing matched" in built["text"]


# ------------------------------------------------------------------- hash ---

def test_the_hash_is_stable_and_covers_the_prompt(corpus):
    out, conn = corpus
    selection = {"runs": [], "maps": [MAP_A], "since": None, "until": None}
    one = scope.build(conn, out, selection, system="SYS")
    two = scope.build(conn, out, selection, system="SYS")
    assert one["hash"] == two["hash"]
    assert scope.build(conn, out, selection, system="OTHER")["hash"] != one["hash"]


def test_the_hash_changes_when_the_corpus_changes(corpus):
    from osu_critique import annotations

    out, conn = corpus
    selection = {"runs": [], "maps": [MAP_A], "since": None, "until": None}
    before = scope.build(conn, out, selection, system="SYS")["hash"]
    annotations.add(out, MAP_A, body="a note that changes the input", scope="map")
    assert scope.build(conn, out, selection, system="SYS")["hash"] != before


# ----------------------------------------------------------------- limits ---

def test_an_oversized_selection_is_flagged_not_refused(corpus, monkeypatch):
    """The threshold is a warning. Owner's call: never block a generation."""
    out, conn = corpus
    monkeypatch.setattr(scope, "MAX_TEXT_BYTES", 100)
    built = scope.build(conn, out, {"runs": [], "maps": [MAP_A], "since": None,
                                    "until": None}, system="SYS")
    assert built["oversized"] is True
    assert built["bytes"] > 100
    assert built["text"].startswith("# Selection summary")

    monkeypatch.setattr(scope, "MAX_TEXT_BYTES", 10_000_000)
    assert scope.build(conn, out, {"runs": [], "maps": [MAP_A], "since": None,
                                   "until": None}, system="SYS")["oversized"] is False


def test_window_presets_resolve_against_now():
    now = datetime(2026, 10, 27, 12, 0, 0)
    start, end = scope.window("today", None, now)
    assert start == "2026-10-27T00:00:00"
    start, end = scope.window("7d", None, now)
    assert start == "2026-10-20T12:00:00"
    start, end = scope.window(None, "2026-10-20", now)
    assert end == "2026-10-21T00:00:00"     # the named day is included


def test_a_question_opens_the_summary_and_changes_the_hash(corpus):
    out, conn = corpus
    plain = {"runs": [], "maps": [MAP_A], "since": None, "until": None}
    asked = dict(plain, question="did I get better at 1/2 jumps?")
    without = scope.build(conn, out, plain, system="SYS")
    with_q = scope.build(conn, out, asked, system="SYS")
    assert with_q["hash"] != without["hash"]              # a different artifact
    assert with_q["text"].startswith("# Selection summary\n\n## The question\n\n"
                                     "did I get better at 1/2 jumps?")
    assert "## The question" not in without["text"]


def test_from_query_keeps_the_question_but_trims_it():
    sel = scope.from_query({"maps": "a", "q": "  did I improve?  "})
    assert sel["question"] == "did I improve?"
    assert scope.from_query({"maps": "a"})["question"] is None


def test_the_trend_block_appears_only_with_enough_plays(corpus):
    out, conn = corpus
    small = scope.build(conn, out, {"maps": [MAP_A, MAP_B], "runs": [], "since": None,
                                    "until": None}, system="SYS")
    assert "## Patterns over time" not in small["text"]     # three plays is not a trend
