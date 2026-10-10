"""Rank-status parsing and classification (the network call is monkeypatched)."""
from __future__ import annotations

import io
import json

import pytest

from osu_critique.io import status as S


def test_classify_buckets():
    assert S.classify("ranked") == "pp-eligible"
    assert S.classify("approved") == "pp-eligible"
    assert S.classify("qualified") == "leaderboard-only"
    assert S.classify("loved") == "leaderboard-only"
    assert S.classify("graveyard") == "unranked"
    assert S.classify("pending") == "unranked"      # pending is not pp-eligible
    assert S.classify(None) is None


def test_beatmap_ids_reads_metadata_and_skips_no_id(tmp_path):
    good = tmp_path / "good.osu"
    good.write_text("osu file format v14\n\n[Metadata]\nTitle:X\nBeatmapID:12345\n")
    zero = tmp_path / "zero.osu"
    zero.write_text("[Metadata]\nBeatmapID:0\n")
    none = tmp_path / "none.osu"
    none.write_text("[Metadata]\nTitle:Y\n")
    idx = {"a" * 32: str(good), "b" * 32: str(zero), "c" * 32: str(none)}
    assert S.beatmap_ids(idx) == {"a" * 32: 12345}


def test_fetch_statuses_parses_the_beatmaps_wrapper(monkeypatch):
    """The batch endpoint returns {"beatmaps": [...]}, not a bare list — the
    first parser read it as a list and broke."""
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=30):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return Resp(json.dumps({"beatmaps": [
            {"id": 1, "status": "ranked", "difficulty_rating": 6.1,
             "beatmapset_id": 9, "ranked": 1},
            {"id": 2, "status": "graveyard", "difficulty_rating": 5.0},
        ]}).encode())

    monkeypatch.setattr(S.urllib.request, "urlopen", fake_urlopen)
    got = S.fetch_statuses([1, 2], "tok")
    assert got[1]["status"] == "ranked" and got[1]["stars"] == 6.1
    assert got[2]["status"] == "graveyard"
    assert "ids[]=1" in seen["url"] and "ids[]=2" in seen["url"]
    assert seen["auth"] == "Bearer tok"


def test_summarise_counts_plays_and_hours():
    rows = [
        {"replay_md5": "r1", "beatmap_md5": "a" * 32, "player": "p",
         "aim_mode": {"duration_s": 120}},
        {"replay_md5": "r2", "beatmap_md5": "b" * 32, "player": "p",
         "aim_mode": {"duration_s": 60}},
        {"replay_md5": "r1", "beatmap_md5": "a" * 32, "player": "p"},  # duplicate
    ]
    cache = {1: {"status": "ranked"}, 2: {"status": "graveyard"}}
    md5_to_id = {"a" * 32: 1, "b" * 32: 2}
    s = S.summarise(rows, cache, md5_to_id, player="p")
    assert s["plays"] == 2 and s["known"] == 2
    assert s["counts"] == {"ranked": 1, "graveyard": 1}
    assert s["hours"]["ranked"] == pytest.approx(120 / 3600.0)
