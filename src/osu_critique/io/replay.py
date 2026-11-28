"""Replay (.osr) loading, frame extraction and lazer score metadata.

A lazer ``.osr`` ends with a compressed ``LegacyReplaySoloScoreInfo`` block
(``online_id``, exact mod settings, per-category hit-result counts and their
maxima, pauses). ``slider`` stops parsing at the frame stream, so the block is
read here directly: it is stdlib only (``lzma`` + ``json``), needs no network
and no credentials, and is the only per-play ground truth the game exposes.

This matters for more than provenance. A rate mod with a custom speed (DT at
1.2x) is exported as a plain DT bit in the legacy header; only this block says
``"speed_change": 1.2``. Without it the player's time base is 1.5x, which is
wrong by 25%.
"""
from __future__ import annotations

import bisect
import json
import lzma
import os
import struct

import slider


def load_replay(replay_path):
    """Load an .osr replay without attaching a beatmap (caller sets .beatmap)."""
    return slider.Replay.from_path(replay_path, retrieve_beatmap=False)


def build_frames(r):
    """list of (time_ms, x, y, keyA_down, keyB_down); keyA = K1|M1, keyB = K2|M2.

    Sorted by time: some export tools append out-of-order
    trailing frames (e.g. a pen-reset frame with an earlier timestamp), which
    would break press detection and cursor interpolation if left unsorted.
    """
    frames = []
    for a in r.actions:
        t = a.offset.total_seconds() * 1000.0
        frames.append((t, a.position.x, a.position.y,
                       bool(a.key1 or a.mouse1), bool(a.key2 or a.mouse2)))
    frames.sort(key=lambda f: f[0])
    return frames


def _uleb128(data, i):
    """Read an osu! ``SerializationReader`` 7-bit length; return (value, next)."""
    value = shift = 0
    while True:
        if i >= len(data):
            raise ValueError("truncated uleb128")
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, i


def _read_string(data, i):
    """Read an osu! string (0x00 = null, 0x0b + uleb128 length + UTF-8)."""
    mode = data[i]
    i += 1
    if mode == 0:
        return None, i
    if mode != 0x0B:
        raise ValueError(f"unknown string prefix {mode:#x}")
    length, i = _uleb128(data, i)
    if i + length > len(data):
        raise ValueError("truncated string")
    return data[i:i + length].decode("utf-8", "replace"), i + length


def _lazer_block_offset(data):
    """Byte offset of the trailing score-info block, or None.

    The header is the legacy ``.osr`` layout; the block is only written for
    format version >= 30000001. Its exact prefix is implementation detail (the
    observed layout is 8 bytes then an int32 length), so the length is tried
    first and a scan for the LZMA-alone header is the fallback.
    """
    try:
        i = 0
        mode = data[i]
        del mode
        i += 1
        version = struct.unpack_from("<i", data, i)[0]
        i += 4
        for _ in range(3):                       # beatmap md5, player, replay md5
            _value, i = _read_string(data, i)
        i += 12                                  # six int16 counts
        i += 4 + 2 + 1 + 4                       # score, max combo, full combo, mods
        _life, i = _read_string(data, i)
        i += 8                                   # timestamp (.NET ticks)
        actions_len = struct.unpack_from("<i", data, i)[0]
        i += 4 + actions_len
        if version < 30000001 or len(data) - i < 12:
            return None
        return i
    except (IndexError, struct.error, ValueError):
        return None


def _lazer_block(data, offset):
    """The LZMA-compressed score-info bytes at ``offset``, or None."""
    tail = data[offset:]
    if len(tail) >= 12:
        n = struct.unpack_from("<i", tail, 8)[0]
        if 0 < n <= len(tail) - 12:
            blob = tail[12:12 + n]
            if blob[:1] == b"\x5d":
                return blob
    # fallback: scan the first 64 bytes for an LZMA-alone stream (5d 00 00 ...)
    for start in range(0, min(64, max(0, len(tail) - 13))):
        if tail[start:start + 3] == b"\x5d\x00\x00":
            return tail[start:]
    return None


def _decompress_score_info(blob):
    try:
        return json.loads(lzma.decompress(blob))
    except (lzma.LZMAError, ValueError, UnicodeDecodeError):
        return None


def _normalise_score_info(raw):
    """The fields this project uses, with the mod rate resolved."""
    mods = [m for m in (raw.get("mods") or []) if isinstance(m, dict)]
    speed_change = None
    for m in mods:
        acronym = str(m.get("acronym") or "").upper()
        settings = m.get("settings") or {}
        if acronym in ("DT", "NC"):
            speed_change = float(settings.get("speed_change") or 1.5)
        elif acronym in ("HT", "DC"):
            speed_change = float(settings.get("speed_change") or 0.75)
    pauses = []
    for p in raw.get("pauses") or []:
        try:
            pauses.append(float(p))
        except (TypeError, ValueError):
            continue
    stats = raw.get("statistics") or {}
    maximum = raw.get("maximum_statistics") or {}
    return {
        "source": "lazer .osr trailing score-info block",
        "client_version": raw.get("client_version"),
        "online_id": raw.get("online_id"),
        "user_id": raw.get("user_id"),
        "rank": raw.get("rank"),
        "mods": mods,
        "speed_change": speed_change,
        "statistics": stats,
        "maximum_statistics": maximum,
        "pauses_ms": pauses,
        "paused": bool(pauses),
        "total_score_without_mods": raw.get("total_score_without_mods"),
    }


def read_header_md5(replay_path):
    """The beatmap md5 from the legacy ``.osr`` header, or None.

    ``slider`` parses the whole file (life bar included) and raises on lazer
    exports whose life-bar offsets are floats (``'8129.88'``). The md5 sits in
    the first bytes, so pairing can still find the map for such a replay even
    though the frame stream cannot be read.
    """
    try:
        with open(os.fspath(replay_path), "rb") as fh:
            data = fh.read(4096)
        value, _i = _read_string(data, 5)
        return value
    except (OSError, IndexError, ValueError):
        return None


def read_score_meta(replay_path):
    """Read the trailing lazer score-info block from a ``.osr`` file.

    Returns a normalised dict, or None for stable-era files and for exports
    that carry no block. Never raises on a malformed file: the replay itself is
    still analysable, only the extra provenance is missing.
    """
    try:
        with open(os.fspath(replay_path), "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    offset = _lazer_block_offset(data)
    if offset is None:
        return None
    blob = _lazer_block(data, offset)
    if blob is None:
        return None
    raw = _decompress_score_info(blob)
    if not isinstance(raw, dict):
        return None
    return _normalise_score_info(raw)


def find_presses(frames):
    """Detect rising edges on either tap button -> list of (time_ms, 'A'|'B')."""
    presses = []
    prev_a = prev_b = False
    for t, x, y, a_down, b_down in frames:
        if a_down and not prev_a:
            presses.append((t, "A"))
        if b_down and not prev_b:
            presses.append((t, "B"))
        prev_a, prev_b = a_down, b_down
    return presses


def cursor_at(frames, times, t):
    """Linear-interpolated (x, y) at time t."""
    i = bisect.bisect_right(times, t)
    if i == 0:
        return frames[0][1], frames[0][2]
    if i >= len(frames):
        return frames[-1][1], frames[-1][2]
    t0, x0, y0, *_ = frames[i - 1]
    t1, x1, y1, *_ = frames[i]
    dt = t1 - t0
    if dt <= 0:
        return x1, y1
    f = (t - t0) / dt
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
