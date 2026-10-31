"""The lazer trailing score-info block: parsing, rate and pauses."""
from __future__ import annotations

import json
import lzma
import struct

import pytest

from osu_critique.io.beatmap import mod_scale
from osu_critique.io.replay import read_score_meta

AAAAA = "tests/fixtures/aaaaa.osr"
SYNTH = "tests/fixtures/synth_clean.osr"


class _Stub:
    double_time = False
    half_time = False


def _uleb(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _cstr(text):
    raw = text.encode()
    return b"\x0b" + _uleb(len(raw)) + raw


def _write_osr(path, *, version=30000016, mods=0, info=None):
    """A minimal legacy .osr with an optional trailing score-info block."""
    actions = lzma.compress(b"", format=lzma.FORMAT_ALONE)
    header = bytearray()
    header += bytes([0])                                  # mode
    header += struct.pack("<i", version)
    header += _cstr("0" * 32)                             # beatmap md5
    header += _cstr("TestPlayer")
    header += _cstr("1" * 32)                             # replay md5
    header += struct.pack("<6h", 10, 1, 0, 0, 0, 1)       # counts
    header += struct.pack("<i", 1000) + struct.pack("<h", 5)
    header += bytes([0]) + struct.pack("<i", mods)
    header += _cstr("")                                   # life bar graph
    header += struct.pack("<q", 0)                        # timestamp
    header += struct.pack("<i", len(actions)) + actions
    if info is not None:
        blob = lzma.compress(json.dumps(info).encode(), format=lzma.FORMAT_ALONE)
        header += b"\xff" * 8 + struct.pack("<i", len(blob)) + blob
    path.write_bytes(bytes(header))
    return path


def test_reads_the_block_from_a_real_lazer_export():
    meta = read_score_meta(AAAAA)
    assert meta is not None
    assert meta["online_id"] == 6931937233
    assert meta["source"].startswith("lazer")
    assert meta["speed_change"] is None
    assert meta["statistics"]["slider_tail_hit"] == 1
    assert meta["maximum_statistics"]["slider_tail_hit"] == 1
    assert meta["paused"] is False


def test_a_synthetic_fixture_without_the_block_returns_none():
    assert read_score_meta(SYNTH) is None


def test_missing_or_truncated_file_degrades_to_none(tmp_path):
    assert read_score_meta(tmp_path / "nope.osr") is None
    broken = tmp_path / "broken.osr"
    broken.write_bytes(open(AAAAA, "rb").read()[:40])
    assert read_score_meta(broken) is None


def test_custom_rate_and_pauses_are_normalised(tmp_path):
    path = _write_osr(tmp_path / "rate.osr", info={
        "client_version": "2026.1.0-lazer",
        "online_id": 42,
        "mods": [{"acronym": "NC", "settings": {"speed_change": 1.2}}],
        "statistics": {"great": 5, "slider_tail_hit": 1},
        "maximum_statistics": {"great": 6, "slider_tail_hit": 2},
        "pauses": [1234.0, 5678.0],
        "total_score_without_mods": 1000,
    })
    meta = read_score_meta(path)
    assert meta["online_id"] == 42
    assert meta["speed_change"] == pytest.approx(1.2)
    assert meta["paused"] is True
    assert meta["pauses_ms"] == [1234.0, 5678.0]
    assert meta["statistics"]["slider_tail_hit"] == 1
    assert meta["maximum_statistics"]["slider_tail_hit"] == 2


def test_default_rate_is_filled_in_for_a_legacy_bitset_mod(tmp_path):
    path = _write_osr(tmp_path / "dt.osr", mods=1 << 6, info={
        "mods": [{"acronym": "DT"}], "statistics": {}, "maximum_statistics": {}})
    assert read_score_meta(path)["speed_change"] == pytest.approx(1.5)


def test_custom_rate_wins_over_the_legacy_flag():
    r = _Stub()
    r.double_time = True
    assert mod_scale(r) == pytest.approx(2 / 3)
    assert mod_scale(r, {"speed_change": 1.2}) == pytest.approx(1 / 1.2)

    r2 = _Stub()
    r2.half_time = True
    assert mod_scale(r2, {"speed_change": 0.75}) == pytest.approx(1 / 0.75)
