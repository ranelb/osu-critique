"""A lazer export with float life-bar offsets must still pair (slider 0.8.4 raises)."""
import shutil
from pathlib import Path

import pytest
import slider

from osu_critique.io import pairing
from osu_critique.io.replay import (_read_string, _uleb128, load_replay,
                                    read_header_md5)

FIX = Path(__file__).parent / "fixtures"


def _float_lifebar_copy(src, dst):
    data = Path(src).read_bytes()
    i = 5
    for _ in range(3):
        _v, i = _read_string(data, i)
    i += 12 + 4 + 2 + 1 + 4
    start = i
    assert data[i] == 0x0B
    n, j = _uleb128(data, i + 1)
    new = b"8129.88|1,9000.5|0.9"
    dst.write_bytes(data[:start] + b"\x0b" + bytes([len(new)]) + new + data[j + n:])


def test_float_lifebar_replay_still_pairs(tmp_path):
    bad = tmp_path / "float.osr"
    _float_lifebar_copy(FIX / "synth_clean.osr", bad)
    with pytest.raises(ValueError):
        slider.Replay.from_path(bad, retrieve_beatmap=False)
    with pytest.raises(ValueError):
        load_replay(bad)
    md5 = read_header_md5(bad)
    assert md5 == read_header_md5(FIX / "synth_clean.osr")
    assert pairing._pair_by_md5([str(bad)], {md5: "map.osu"}, "t") == [(str(bad), "map.osu")]


def test_header_md5_of_garbage_is_none(tmp_path):
    junk = tmp_path / "junk.osr"
    junk.write_bytes(b"\x00\x01")
    assert read_header_md5(junk) is None
    assert pairing._pair_by_md5([str(junk)], {}, "t") == []
