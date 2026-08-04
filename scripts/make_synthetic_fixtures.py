#!/usr/bin/env python3
"""Generate synthetic .osu/.osr fixture pairs for edge-case tests, and
anonymize real replay fixtures.

Ground truth is known (we write the play), so tests can assert exact counts.

Usage:
    python scripts/make_synthetic_fixtures.py            # (re)generate synth_* fixtures
    python scripts/make_synthetic_fixtures.py --anonymize   # rename player in real .osr fixtures

The .osr binary layout mirrors slider's parser (see src/osu_critique/io/replay.py):
header fields, osu!-strings (0x0b + uleb length + bytes), and LZMA-compressed
CSV actions "delta_ms|x|y|mask" (delta relative to previous action; K1=5, K2=10).
"""
from __future__ import annotations

import hashlib
import lzma
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"

# mod bits (osu! standard)
NF, EZ, TD, HD, HR, SD, DT, RX, HT, NC, FL, AT, SO, AP, PF = (
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384)


# ------------------------------------------------------------- binary ------

def uleb(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def ostring(s: str) -> bytes:
    if not s:
        return b"\x00"
    b = s.encode("utf-8")
    return b"\x0b" + uleb(len(b)) + b


def i16(n): return struct.pack("<h", n)
def i32(n): return struct.pack("<i", n)
def i64(n): return struct.pack("<q", n)


def make_osr(player, beatmap_md5, counts, score, combo, perfect, mods, actions):
    """actions: list of (delta_ms, x, y, mask); delta relative to previous action."""
    body = ",".join(f"{dt}|{x:.3f}|{y:.3f}|{mask}" for dt, x, y, mask in actions)
    compressed = lzma.compress(body.encode("utf-8"))
    buf = bytearray()
    buf += b"\x00"                                       # mode: osu!
    buf += i32(20260804)                                 # game version
    buf += ostring(beatmap_md5)
    buf += ostring(player)
    buf += ostring("0" * 32)                             # replay md5 (unused)
    buf += i16(counts[0]) + i16(counts[1]) + i16(counts[2]) + i16(0) + i16(0) + i16(counts[3])
    buf += i32(score)
    buf += i16(combo)
    buf += b"\x01" if perfect else b"\x00"
    buf += i32(mods)
    buf += ostring("0|100")                              # life bar graph (non-empty)
    buf += i64(0)                                        # timestamp
    buf += i32(len(compressed))
    buf += compressed
    buf += i32(0) + i32(0)                               # seed, online score id
    return bytes(buf)


def anonymize_osr(data: bytes, new_name: str) -> bytes:
    """Replace the player-name string in an .osr (keeps all other data)."""
    i = 1 + 4  # mode + version

    def parse_string(i):
        """Returns (content, start_index_incl_prefix, end_index_excl_content)."""
        start = i
        m = data[i]
        i += 1
        if m == 0:
            return None, start, i
        length = 0
        shift = 0
        while True:
            b = data[i]
            i += 1
            length |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return data[i:i + length].decode("utf-8"), start, i + length

    _, _, i = parse_string(i)        # beatmap md5 -> i = end of its content
    _, name_start, name_end = parse_string(i)  # player name span (incl. prefix)
    return data[:name_start] + ostring(new_name) + data[name_end:]


# -------------------------------------------------------------- maps -------

def make_osu(title, circles, first_t=1000, interval=500):
    lines = [
        "osu file format v14", "",
        "[General]", "AudioFilename: dummy.mp3", "AudioLeadIn: 0", "PreviewTime: -1",
        "Countdown: 0", "SampleSet: Soft", "StackLeniency: 0.7", "Mode: 0", "",
        "[Metadata]", f"Title:{title}", f"TitleUnicode:{title}", "Artist:synthetic",
        "ArtistUnicode:synthetic", "Creator:osu-critique", "Version:test", "",
        "[Difficulty]", "HPDrainRate:5", "CircleSize:4", "OverallDifficulty:8",
        "ApproachRate:9", "SliderMultiplier:1.4", "SliderTickRate:1", "",
        "[TimingPoints]", "0,500,4,2,1,25,1,0", "",
        "[HitObjects]",
    ]
    t = first_t
    for (x, y) in circles:
        lines.append(f"{x},{y},{t},1,0")
        t += interval
    text = "\n".join(lines) + "\n"
    return text, hashlib.md5(text.encode("utf-8")).hexdigest()


def play_actions(times, errors, scale=1.0, positions=None, trailing=None):
    """Press/release frames. scale maps map-time -> real-time (mods).
    trailing: optional (t_ms, x, y) frame appended out of order (danser artifact)."""
    actions = []
    prev_t = 0.0

    def emit(t, x, y, mask):
        nonlocal prev_t
        actions.append((int(round(t - prev_t)), x, y, mask))
        prev_t = t

    for i, (mt, err, (x, y)) in enumerate(zip(times, errors, positions)):
        pt = mt * scale + err
        mask = 5 if i % 2 == 0 else 10  # alternate K1/K2
        emit(pt, x, y, mask)
        emit(pt + 1, x, y, 0)           # release
    if trailing:
        emit(*trailing)
    return actions


# -------------------------------------------------------------- main -------

def gen_circles(n, first_t=1000, interval=500):
    xs = [100.0 if i % 2 == 0 else 400.0 for i in range(n)]
    ys = [192.0] * n
    return list(zip(xs, ys)), [first_t + i * interval for i in range(n)]


# known result: 17x300 / 2x100 / 1x50 / 0 miss — errors must fall inside the
# *scaled* OD-8 windows: clean w300=32/w100=76/w50=120, HT x4/3, DT x2/3
def clean_errors(n, err100=40.0, err50=90.0):
    errs = [0.0] * n
    errs[7] = err100
    errs[13] = err100
    errs[19] = err50
    return errs


def generate():
    FIX.mkdir(parents=True, exist_ok=True)

    circles, times = gen_circles(20)
    for name, mods, scale, errs in (
        ("synth_clean", 0, 1.0, clean_errors(20)),
        ("synth_htm", HT, 4.0 / 3.0, clean_errors(20, 60.0, 120.0)),
        ("synth_dt", DT, 2.0 / 3.0, clean_errors(20, 35.0, 70.0)),
    ):
        text, md5 = make_osu(name, circles)
        (FIX / f"{name}.osu").write_text(text)
        acts = play_actions(times, errs, scale=scale, positions=circles)
        (FIX / f"{name}.osr").write_bytes(make_osr("TestPlayer", md5, (17, 2, 1, 0), 123456, 20, False, mods, acts))

    # map-version mismatch / failed play: 40-circle map, play covers first 20
    circles2, times2 = gen_circles(40)
    text, md5 = make_osu("synth_mismatch", circles2)
    (FIX / "synth_mismatch.osu").write_text(text)
    acts = play_actions(times[:20], clean_errors(20), positions=circles[:20])
    (FIX / "synth_mismatch.osr").write_bytes(make_osr("TestPlayer", md5, (17, 2, 1, 0), 123456, 20, False, 0, acts))

    # out-of-order trailing frame (danser artifact): must not break detection
    text, md5 = make_osu("synth_oooframes", circles)
    (FIX / "synth_oooframes.osu").write_text(text)
    acts = play_actions(times, clean_errors(20), positions=circles, trailing=(5100.0, 250.0, 192.0, 0))
    (FIX / "synth_oooframes.osr").write_bytes(make_osr("TestPlayer", md5, (17, 2, 1, 0), 123456, 20, False, 0, acts))

    print(f"wrote synthetic fixtures to {FIX}")


def anonymize_fixtures():
    for name in ("aaaaa", "domino", "deafheaven"):
        p = FIX / f"{name}.osr"
        data = p.read_bytes()
        new = anonymize_osr(data, "TestPlayer")
        p.write_bytes(new)
        print(f"anonymized {name}.osr ({len(data)} -> {len(new)} bytes)")


if __name__ == "__main__":
    if "--anonymize" in sys.argv:
        anonymize_fixtures()
    else:
        generate()
