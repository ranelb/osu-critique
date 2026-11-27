"""Tests for the recommender: skill profile, buckets, gates, blacklist.

Everything here builds a controlled corpus (library rows + runs) so each verdict
is checked against numbers the test chose, not against the owner's real plays.
Helpers open and close their own connections: holding a write connection open
while another write opens would just trade assertions for "database is locked".
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from osu_critique import blacklist, index, library, recommend


def ago(days: float) -> str:
    return (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")


def map_row(md5, *, sr=5.0, mode=0, length_ms=90_000, n_objects=300,
            set_id=None, title=None, speed=0.3, **feats):
    """A feature dict for ``library.upsert``: only the fields the scorer reads."""
    doc = {
        "beatmap_md5": md5, "map_path": f"/maps/{md5}.osu", "feature_version": library.FEATURE_VERSION,
        "set_id": set_id, "beatmap_id": None, "mode": mode,
        "title": title or md5, "artist": "artist", "creator": "mapper",
        "version": "Insane", "sr": sr, "bpm": 180.0, "length_ms": length_ms,
        "ar": 9.0, "od": 8.0, "cs": 4.0, "hp": 5.0,
        "n_objects": n_objects, "n_circles": n_objects, "n_sliders": 0,
        "n_spinners": 0, "slider_ratio": 0.2, "density": 3.0,
        "dense_share": 0.2, "stream_share": 0.2, "jump_share": 0.2,
        "bigjump_share": 0.2, "anti_flow_share": 0.2, "flow_share": 0.2,
        "kiai_share": 0.0, "strain_aim_max": 10.0, "strain_speed_max": 10.0,
        "sustained_share": 0.3, "sustained_max": 20, "sustained_nps": 6.0,
        # the features the scorer reads: rosu-pp attributes and the class shares
        "rosu": {"stars": sr, "aim": 2.0, "speed": 2.0, "slider_factor": 0.95,
                 "speed_note_count": speed * n_objects,
                 "aim_difficult_strain_count": 40.0,
                 "speed_difficult_strain_count": 40.0},
        "classes": {"any_shape": 0.0, "any_walk": 0.05, "any_curve": 0.05,
                    "keys": {"leg:wide/snap": 0.1}},
    }
    doc.update(feats)
    return doc


def add_map(outdir, md5, **kwargs):
    conn = index.connect(index.db_path(outdir))
    try:
        library.upsert(conn, map_row(md5, **kwargs), mtime=1.0, size=1)
        conn.commit()
    finally:
        conn.close()


def add_run(outdir, md5, *, accuracy=0.95, miss=0, n_objects=300,
            played_at=None, player="you", tag=None, failed=False, relax=False):
    tag = tag or f"{md5[:6]}_{accuracy}_{played_at or 'now'}"
    doc = {
        "schema_version": 1, "tag": tag, "beatmap_md5": md5,
        "replay_md5": tag.ljust(32, "0")[:32],
        "played_at": played_at or ago(5), "player": player,
        "map": f"{md5} [Insane]", "mod_string": "RX" if relax else "NM",
        "mods": {"RX": relax}, "time_scale": 1.0,
        "difficulty": {"CS": 4.0, "AR": 9.0, "OD": 8.0, "HP": 5.0},
        "n_objects": n_objects, "n_objects_map": n_objects,
        "accuracy": accuracy, "max_combo": 100, "full_combo": False,
        "ur": 120.0, "ur_pct_of_300_window": 50.0,
        "hit_error_ms": {"mean": 0.0, "std": 20.0, "p10": -20.0, "p90": 20.0},
        "counts_recorded": {"300": n_objects - miss, "100": 0, "50": 0, "miss": miss},
        "counts_detected": {"300": n_objects - miss, "100": 0, "50": 0, "miss": miss},
        "trust": {"trustworthy": True, "abs_delta_total": 0, "judged": n_objects},
        "failed_play": failed, "time_base": {"overridden": False},
        "aim_mode": {"is_relax": relax},
    }
    path = Path(outdir) / f"{tag}_metrics.json"
    path.write_text(json.dumps(doc))
    conn = index.connect(index.db_path(outdir))
    try:
        index.upsert_run(doc, path, outdir=outdir, conn=conn)
    finally:
        conn.close()


# ------------------------------------------------------------ skill profile --

def test_default_player_is_the_most_run_one(tmp_path):
    for i in range(3):
        add_run(tmp_path, "a" * 32, player="you", tag=f"you{i}")
    add_run(tmp_path, "a" * 32, player="someone", tag="someone0")
    conn = index.open_readonly(tmp_path)
    try:
        assert recommend.default_player(conn) == "you"
    finally:
        conn.close()


def test_weakness_comes_from_the_worse_half_of_a_material(tmp_path):
    for i, nps in enumerate((12.0, 12.0, 12.0, 3.0, 3.0, 3.0)):
        md5 = f"{i:032x}"
        add_map(tmp_path, md5, sr=5.0, speed=nps / 15)
        miss = 24 if nps > 6 else 6          # 8% vs 2% of 300 objects
        for j in range(10):
            add_run(tmp_path, md5, accuracy=0.90, miss=miss,
                    played_at=ago(10 + j), tag=f"{i}-{j}")

    result = recommend.build(tmp_path, player="you", limit=5)
    skills = result["skills"]
    assert result["basis"] == "weakness"
    weakness = skills["weaknesses"][0]
    assert weakness["key"] == "speed_notes"
    assert weakness["bad_side"] == "high"
    assert weakness["gap_pp"] > 0.5
    assert weakness["n_bad"] >= recommend.MIN_SIDE
    assert weakness["n_good"] >= recommend.MIN_SIDE
    # the evidence is the miss rate, and both halves are quoted
    assert weakness["miss_bad_pct"] > weakness["miss_good_pct"]


def test_no_weakness_when_the_halves_behave_identically(tmp_path):
    for i, nps in enumerate((12.0, 12.0, 12.0, 3.0, 3.0, 3.0)):
        md5 = f"{i:032x}"
        add_map(tmp_path, md5, sr=5.0, speed=nps / 15)
        for j in range(10):
            add_run(tmp_path, md5, accuracy=0.90, miss=15,
                    played_at=ago(10 + j), tag=f"{i}-{j}")

    result = recommend.build(tmp_path, player="you", limit=5)
    assert result["basis"] == "difficulty-only"
    assert result["skills"]["weaknesses"] == []


def test_a_thin_side_is_not_a_weakness(tmp_path):
    """14 runs on one side is below MIN_SIDE and must not become a verdict."""
    for i, nps in enumerate((12.0, 3.0)):
        md5 = f"{i:032x}"
        add_map(tmp_path, md5, sr=5.0, speed=nps / 15)
        for j in range(14):
            add_run(tmp_path, md5, accuracy=0.90, miss=24 if nps > 6 else 2,
                    played_at=ago(10 + j), tag=f"{i}-{j}")
    result = recommend.build(tmp_path, player="you", limit=5)
    assert result["skills"]["weaknesses"] == []


def test_relax_runs_are_counted_and_excluded(tmp_path):
    for i in range(4):
        md5 = f"{i:032x}"
        add_map(tmp_path, md5, sr=5.0, speed=0.7)
        for j in range(6):
            add_run(tmp_path, md5, accuracy=0.9, miss=20, relax=True,
                    played_at=ago(10 + j), tag=f"rx{i}-{j}")
    result = recommend.build(tmp_path, player="you", limit=5)
    assert result["skills"]["n_runs"] == 0
    assert result["skills"]["excluded_relax"] == 24
    assert result["recommendations"] == []


def test_miss_rate_is_band_corrected(tmp_path):
    """Harder maps must not look like "wrong material".

    Two materials, both played in the *same* band, with identical excess miss
    rates: no weakness. The same corpus with one material shifted inside a
    harder band would otherwise show a fake difference.
    """
    for i in range(4):
        md5 = f"{i:032x}"
        add_map(tmp_path, md5, sr=5.0, speed=0.7 if i < 2 else 0.2)
        for j in range(10):
            add_run(tmp_path, md5, accuracy=0.90, miss=20,
                    played_at=ago(10 + j), tag=f"{i}-{j}")
    result = recommend.build(tmp_path, player="you", limit=5)
    assert result["skills"]["weaknesses"] == []


# ----------------------------------------------------------------- buckets --

def bucket_corpus(tmp_path):
    """Five eligible maps covering every bucket and every gate."""
    # good runs, last one 40 days ago: not an improver, and nothing else claims it
    add_map(tmp_path, "1" * 32, sr=5.0, set_id=101, title="stale-good")
    for j, days in enumerate((50, 45, 40)):
        add_run(tmp_path, "1" * 32, accuracy=0.96, played_at=ago(days), tag=f"m{j}")
    # improver: recent good runs, then a collapse
    add_map(tmp_path, "2" * 32, sr=5.0, set_id=102, title="improver")
    for j, acc in enumerate((0.96, 0.95, 0.94, 0.95, 0.94, 0.80)):
        add_run(tmp_path, "2" * 32, accuracy=acc, played_at=ago(20 - j), tag=f"i{j}")
    # new: never played
    add_map(tmp_path, "3" * 32, sr=5.0, set_id=103, title="new")
    # played, but well and recently: neither
    add_map(tmp_path, "4" * 32, sr=5.0, set_id=104, title="neutral")
    add_run(tmp_path, "4" * 32, accuracy=0.97, played_at=ago(2), tag="n0")
    add_run(tmp_path, "4" * 32, accuracy=0.97, played_at=ago(1), tag="n1")
    # gated: mania, too short, out of the band, too few objects
    add_map(tmp_path, "5" * 32, sr=5.0, mode=3, title="mania")
    add_map(tmp_path, "6" * 32, sr=5.0, length_ms=20_000, title="short")
    add_map(tmp_path, "7" * 32, sr=9.0, title="too hard")
    add_map(tmp_path, "8" * 32, sr=5.0, n_objects=80, title="too small")
    return tmp_path


def test_buckets_are_classified_by_evidence(tmp_path):
    bucket_corpus(tmp_path)
    result = recommend.build(tmp_path, player="you", limit=10)
    buckets = {c["title"]: c["bucket"] for c in result["recommendations"]}
    assert "stale-good" not in buckets
    assert buckets["improver"] == "improver"
    assert buckets["new"] == "new"
    assert "neutral" not in buckets
    for gated in ("mania", "short", "too hard", "too small"):
        assert gated not in buckets


def test_improver_card_carries_the_proof(tmp_path):
    bucket_corpus(tmp_path)
    result = recommend.build(tmp_path, player="you", limit=10)
    card = next(c for c in result["recommendations"] if c["bucket"] == "improver")
    assert card["best_accuracy"] == pytest.approx(96.0)
    assert card["latest_accuracy"] == pytest.approx(80.0)
    assert card["n_attempts"] == 6
    assert card["band_median_accuracy"] > 80.0
    assert "best 96.0%" in card["why"]
    assert "last attempt 80.0%" in card["why"]


def test_there_is_no_maintain_bucket(tmp_path):
    """Held-out runs show no decay with time away, so age alone recommends nothing."""
    add_map(tmp_path, "a" * 32, sr=5.0, title="old-good")
    for j, days in enumerate((300, 250, 200, 190, 180, 170)):
        add_run(tmp_path, "a" * 32, accuracy=0.96, played_at=ago(days), tag=f"f{j}")
    result = recommend.build(tmp_path, player="you", limit=5)
    assert all(c["bucket"] != "maintain" for c in result["recommendations"])
    assert "maintain" not in result["counts"]


def test_improver_has_no_gap_cutoff(tmp_path):
    """Any latest attempt below the band median counts; a bigger gap only ranks higher."""
    add_map(tmp_path, "d" * 32, sr=5.0, set_id=201, title="barely")
    add_map(tmp_path, "e" * 32, sr=5.0, set_id=202, title="far")
    for j, acc in enumerate((0.96, 0.96, 0.96, 0.955)):
        add_run(tmp_path, "d" * 32, accuracy=acc, played_at=ago(20 - j), tag=f"d{j}")
    for j, acc in enumerate((0.96, 0.96, 0.96, 0.85)):
        add_run(tmp_path, "e" * 32, accuracy=acc, played_at=ago(20 - j), tag=f"e{j}")
    cards = {c["title"]: c for c in recommend.build(
        tmp_path, player="you", limit=10)["recommendations"]}
    assert cards["barely"]["bucket"] == cards["far"]["bucket"] == "improver"
    assert cards["far"]["score"] > cards["barely"]["score"]


def test_bucket_filter_is_honoured(tmp_path):
    bucket_corpus(tmp_path)
    result = recommend.build(tmp_path, player="you", limit=10, buckets=["new"])
    assert result["recommendations"]
    assert {c["bucket"] for c in result["recommendations"]} == {"new"}


def test_one_difficulty_per_set(tmp_path):
    add_map(tmp_path, "b" * 32, sr=5.0, set_id=77, title="set-a")
    add_map(tmp_path, "c" * 32, sr=5.4, set_id=77, title="set-b")
    result = recommend.build(tmp_path, player="you", limit=10)
    titles = [c["title"] for c in result["recommendations"]]
    assert len(titles) == 1 and titles[0] in {"set-a", "set-b"}


def test_selection_interleaves_buckets(tmp_path):
    bucket_corpus(tmp_path)
    result = recommend.build(tmp_path, player="you", limit=3)
    assert [c["bucket"] for c in result["recommendations"]] == [
        "new", "improver"]


def test_build_is_deterministic(tmp_path):
    bucket_corpus(tmp_path)
    first = recommend.build(tmp_path, player="you", limit=10)
    second = recommend.build(tmp_path, player="you", limit=10)
    assert first == second


def test_without_an_index_build_says_so(tmp_path):
    result = recommend.build(tmp_path)
    assert "error" in result and result["recommendations"] == []


# --------------------------------------------------------------- blacklist --

def test_blacklist_sidecar_roundtrip(tmp_path):
    assert blacklist.is_blocked(blacklist.load(tmp_path), "a" * 32) is False
    blacklist.add_map(tmp_path, "a" * 32)
    blacklist.add_set(tmp_path, 4242)
    doc = blacklist.load(tmp_path)
    assert doc["maps"] == ["a" * 32] and doc["sets"] == [4242]
    assert blacklist.is_blocked(doc, "a" * 32) is True
    assert blacklist.is_blocked(doc, "b" * 32, 4242) is True
    assert blacklist.is_blocked(doc, "b" * 32, 1) is False
    blacklist.remove_map(tmp_path, "a" * 32)
    blacklist.remove_set(tmp_path, 4242)
    doc = blacklist.load(tmp_path)
    assert doc["maps"] == [] and doc["sets"] == []


def test_blacklist_malformed_file_means_nothing_blocked(tmp_path):
    (tmp_path / "blacklist.json").write_text("{not json")
    assert blacklist.load(tmp_path)["maps"] == []


def test_recommendation_skips_a_blacklisted_map(tmp_path):
    bucket_corpus(tmp_path)
    blacklist.add_map(tmp_path, "3" * 32)
    result = recommend.build(tmp_path, player="you", limit=10)
    assert all(c["title"] != "new" for c in result["recommendations"])
    assert result["counts"]["blocked"] >= 1
    loose = recommend.build(tmp_path, player="you", limit=10, use_blacklist=False)
    assert any(c["title"] == "new" for c in loose["recommendations"])


def test_blacklist_set_blocks_every_difficulty(tmp_path):
    bucket_corpus(tmp_path)
    blacklist.add_set(tmp_path, 103)
    result = recommend.build(tmp_path, player="you", limit=10)
    assert all(c["title"] != "new" for c in result["recommendations"])


def test_blacklist_mirrors_into_the_index(tmp_path):
    bucket_corpus(tmp_path)
    blacklist.add_map(tmp_path, "3" * 32)
    conn = index.connect(index.db_path(tmp_path))
    try:
        blacklist.mirror(conn, tmp_path)
        keys = {r["key"] for r in conn.execute("SELECT key FROM blacklist")}
        assert "3" * 32 in keys
    finally:
        conn.close()


# --------------------------------------------------------------------- cli --

def test_cli_blacklist_and_recommend(tmp_path, capsys):
    from osu_critique import cli

    bucket_corpus(tmp_path)
    assert cli.main(["blacklist", "add", "--map", "3" * 32,
                     "--outdir", str(tmp_path)]) == 0
    conn = index.connect(index.db_path(tmp_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM blacklist").fetchone()[0] == 1
    finally:
        conn.close()
    capsys.readouterr()

    assert cli.main(["recommend", "--json", "--outdir", str(tmp_path),
                     "--player", "you"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["player"] == "you"
    assert all(c["title"] != "new" for c in payload["recommendations"])


def test_cli_blacklist_list(tmp_path, capsys):
    from osu_critique import cli

    blacklist.add_map(tmp_path, "d" * 32)
    assert cli.main(["blacklist", "list", "--outdir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "1 maps" in out and "d" * 32 in out


def test_an_unscanned_library_is_reported_not_silently_empty(tmp_path):
    add_run(tmp_path, "a" * 32)
    result = recommend.build(tmp_path, player="you")
    assert "library scan" in result["error"]
    assert result["recommendations"] == []
