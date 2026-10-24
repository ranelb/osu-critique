"""Tests for the ``.osu`` metadata reader (map pages + the beatmaps table)."""
from __future__ import annotations

from pathlib import Path

from osu_critique import mapmeta

FIXTURES = Path(__file__).parent / "fixtures"


def test_reads_the_title_block_and_background():
    meta = mapmeta.parse_file(FIXTURES / "deafheaven.osu")
    assert meta["Title"] == "DEAFHEAVEN"
    assert meta["Artist"] == "inoqx"
    assert meta["Creator"] == "namriee"
    assert meta["Version"] == "EXTREME COLLAB"
    # CRLF line endings must not leak into the values
    assert "\r" not in meta["Version"]
    assert meta["background"] == "136969250_p0.jpg"
    assert meta["mode"] == 0
    assert meta["audio"] == "audio.mp3"


def test_ids_are_ints_or_none():
    meta = mapmeta.parse_file(FIXTURES / "deafheaven.osu")
    for key in ("BeatmapID", "BeatmapSetID"):
        assert meta[key] is None or isinstance(meta[key], int)


def test_bom_is_tolerated():
    # aaaaa.osu starts with a UTF-8 BOM; a naive reader loses [General].
    meta = mapmeta.parse_file(FIXTURES / "aaaaa.osu")
    assert meta["Title"], "BOM swallowed the first section"
    assert meta["Version"]


def test_missing_file_is_not_an_error():
    meta = mapmeta.parse_file(FIXTURES / "does-not-exist.osu")
    assert meta["Title"] is None
    assert meta["background"] is None
    assert meta["BeatmapID"] is None


def test_events_only_takes_a_background_not_a_video_or_break():
    text = "\n".join([
        "osu file format v14",
        "[Events]",
        '//Background and Video events',
        '1,0,"intro.mp4"',
        '0,0,"bg.jpg",0,0',
        '2,41234,50000',
        "[Metadata]",
        "Title:  Padded Title  ",
        "BeatmapSetID: 12345",
    ])
    meta = mapmeta.parse_text(text)
    assert meta["background"] == "bg.jpg"
    assert meta["Title"] == "Padded Title"
    assert meta["BeatmapSetID"] == 12345


def test_no_metadata_section_means_all_none():
    meta = mapmeta.parse_text("osu file format v14\n[General]\nMode: 3\n")
    assert meta["Title"] is None
    assert meta["mode"] == 3


def test_display_name_prefers_unicode_and_appends_the_difficulty():
    meta = {"Artist": "a", "ArtistUnicode": "A", "Title": "t",
            "TitleUnicode": "T", "Version": "Insane"}
    assert mapmeta.display_name(meta) == "A - T [Insane]"
    assert mapmeta.display_name({}, fallback="fallback") == "fallback"
    assert mapmeta.display_name({"Artist": "a", "Title": "t"}) == "a - t"
