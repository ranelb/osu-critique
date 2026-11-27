#!/usr/bin/env python3
"""Generate synthetic .osu maps whose geometric patterns are known by construction.

Each map is ``<name>.osu`` plus ``<name>.labels.json``. A label says which shape
sits at which time range (map ms), e.g. a clockwise triangle from 4000 to 5000.
Everything between labelled blocks is *junk*: irregular filler that must not be
labelled. The same label format is used to hand-label real maps, so
``scripts/eval_patterns.py`` scores both the same way.

Usage:
    python scripts/make_pattern_fixtures.py    # (re)writes tests/fixtures/patterns/

Deterministic: fixed seeds, no wall clock, so regenerating changes nothing.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "patterns"

CS = 4.0
RADIUS = 54.4 - 4.48 * CS          # osu! circle radius in playfield px (CS 4 -> 36.5)
BPM = 180.0
BEAT_MS = 60000.0 / BPM
FIELD = (512.0, 384.0)
MARGIN = 24.0


def _inside(points):
    return all(MARGIN <= x <= FIELD[0] - MARGIN and MARGIN <= y <= FIELD[1] - MARGIN
               for x, y in points)


# ------------------------------------------------------------------ blocks --
# Each returns (points, label) where label is (shape, dir or None) or None for
# junk. ``rng`` places and rotates; ``side`` is the leg length in radii.

def line(rng, side, n=7):
    a = rng.uniform(0, 2 * math.pi)
    d = side * RADIUS
    x0 = rng.uniform(MARGIN, FIELD[0] - MARGIN)
    y0 = rng.uniform(MARGIN, FIELD[1] - MARGIN)
    return [(x0 + i * d * math.cos(a), y0 + i * d * math.sin(a)) for i in range(n)], ("line", None)


def back_and_forth(rng, side, n=8):
    a = rng.uniform(0, 2 * math.pi)
    d = side * RADIUS
    cx = rng.uniform(MARGIN + d, FIELD[0] - MARGIN - d)
    cy = rng.uniform(MARGIN + d, FIELD[1] - MARGIN - d)
    p, q = (cx - d / 2 * math.cos(a), cy - d / 2 * math.sin(a)), \
           (cx + d / 2 * math.cos(a), cy + d / 2 * math.sin(a))
    return [p if i % 2 == 0 else q for i in range(n)], ("back_and_forth", None)


def polygon(rng, k, side, cw, reps=2):
    """k-gon with ``reps`` laps (+ the closing vertex), side in radii."""
    big_r = side * RADIUS / (2 * math.sin(math.pi / k))
    cx = rng.uniform(MARGIN + big_r, FIELD[0] - MARGIN - big_r)
    cy = rng.uniform(MARGIN + big_r, FIELD[1] - MARGIN - big_r)
    rot = rng.uniform(0, 2 * math.pi)
    sign = 1.0 if cw else -1.0     # y points down: increasing angle is clockwise
    verts = [(cx + big_r * math.cos(rot + sign * 2 * math.pi * j / k),
              cy + big_r * math.sin(rot + sign * 2 * math.pi * j / k)) for j in range(k)]
    pts = [verts[i % k] for i in range(k * reps + 1)]
    name = {3: "triangle", 4: "square", 5: "pentagon", 6: "hexagon"}[k]
    return pts, (name, "cw" if cw else "ccw")


def star(rng, side, cw=True, reps=2):
    """Five-pointed star drawn as a pentagram: every second vertex, two laps."""
    big_r = side * RADIUS / (2 * math.sin(2 * math.pi / 5))     # chord of 144 deg
    cx = rng.uniform(MARGIN + big_r, FIELD[0] - MARGIN - big_r)
    cy = rng.uniform(MARGIN + big_r, FIELD[1] - MARGIN - big_r)
    rot = rng.uniform(0, 2 * math.pi)
    sign = 1.0 if cw else -1.0
    order = [0, 2, 4, 1, 3]
    verts = [(cx + big_r * math.cos(rot + sign * 2 * math.pi * k / 5),
              cy + big_r * math.sin(rot + sign * 2 * math.pi * k / 5)) for k in order]
    return [verts[i % 5] for i in range(5 * reps + 1)], ("star", "cw" if cw else "ccw")


def circle(rng, side, cw=True, n=None):
    """One lap; with ``n`` unset, as many notes as fit in the 384 px playfield."""
    if n is None:
        n = next((k for k in range(14, 7, -1)
                  if side * RADIUS / math.sin(math.pi / k) <= FIELD[1] - 2 * MARGIN), 8)
    step = 2 * math.pi / n
    big_r = side * RADIUS / (2 * math.sin(step / 2))
    cx = rng.uniform(MARGIN + big_r, FIELD[0] - MARGIN - big_r)
    cy = rng.uniform(MARGIN + big_r, FIELD[1] - MARGIN - big_r)
    sign = 1.0 if cw else -1.0
    # n + 1 points: the lap closes back on its first note, so the sweep is a full 360
    return [(cx + big_r * math.cos(sign * step * i), cy + big_r * math.sin(sign * step * i))
            for i in range(n + 1)], ("circle", "cw" if cw else "ccw")


def arc(rng, side, cw=True, n=7, turn_deg=20.0):
    """Part of a circle; placed from its first point so a big radius still fits."""
    step = math.radians(turn_deg)
    big_r = side * RADIUS / (2 * math.sin(step / 2))
    sx = rng.uniform(MARGIN, FIELD[0] - MARGIN)
    sy = rng.uniform(MARGIN, FIELD[1] - MARGIN)
    toward = rng.uniform(0, 2 * math.pi)
    cx, cy = sx + big_r * math.cos(toward), sy + big_r * math.sin(toward)
    sign = 1.0 if cw else -1.0
    rot = toward + math.pi
    return [(cx + big_r * math.cos(rot + sign * step * i),
             cy + big_r * math.sin(rot + sign * step * i)) for i in range(n)], \
           ("arc", "cw" if cw else "ccw")


def zigzag(rng, side, n=8, swing_deg=55.0):
    base = rng.uniform(0, 2 * math.pi)
    d = side * RADIUS
    x, y = rng.uniform(MARGIN, FIELD[0] - MARGIN), rng.uniform(MARGIN, FIELD[1] - MARGIN)
    pts = [(x, y)]
    for i in range(n - 1):
        h = base + math.radians(swing_deg) * (1 if i % 2 == 0 else -1)
        x, y = x + d * math.cos(h), y + d * math.sin(h)
        pts.append((x, y))
    return pts, ("zigzag", None)


def stack(rng, n=5):
    x, y = rng.uniform(MARGIN, FIELD[0] - MARGIN), rng.uniform(MARGIN, FIELD[1] - MARGIN)
    return [(x + (i % 2), y) for i in range(n)], ("stack", None)


def junk(rng, n, prev, avoid=()):
    """Irregular filler with no repeating, constant-turn or straight structure.

    Rejection sampling on local relations only (turns and lengths), so the
    generator does not depend on the classifier it is used to test.
    """
    pts = [prev]
    turns, lens, heading = [], [], rng.uniform(0, 2 * math.pi)
    tries = 0
    while len(pts) < n + 1 and tries < 20000:
        tries += 1
        turn = rng.choice([-1, 1]) * rng.uniform(25, 130)
        length = rng.uniform(1.8, 7.0)
        if turns:
            t0, l0 = turns[-1], lens[-1]
            if abs(abs(turn) - abs(t0)) < 22:                    # regular corners
                continue
            if max(length, l0) / min(length, l0) < 1.35:         # regular legs
                continue
        h = heading + math.radians(turn)
        x = pts[-1][0] + length * RADIUS * math.cos(h)
        y = pts[-1][1] + length * RADIUS * math.sin(h)
        if not _inside([(x, y)]):
            continue
        # no near-repeat of a recent position (that would be a cycle)
        if any(math.hypot(x - px, y - py) < 1.6 * RADIUS for px, py in pts[-7:]):
            continue
        # and none of the blocks on either side: junk that lands on a vertex of the
        # next shape really does draw a back-and-forth with it
        if any(math.hypot(x - px, y - py) < 1.6 * RADIUS for px, py in avoid):
            continue
        pts.append((x, y))
        turns.append(turn)
        lens.append(length)
        heading = h
    return pts[1:], None


# --------------------------------------------------------------------- maps --

def build(name, seed, plan, gap_ms, jitter_r=0.0, junk_n=6):
    """``plan`` is a list of (builder, kwargs); junk goes between and around."""
    rng = random.Random(seed)
    objects, blocks = [], []
    t = 1000.0
    last = (FIELD[0] / 2, FIELD[1] / 2)

    def emit(points, label):
        nonlocal t, last
        t0 = t
        for x, y in points:
            jx = rng.gauss(0, jitter_r * RADIUS) if jitter_r and label else 0.0
            jy = rng.gauss(0, jitter_r * RADIUS) if jitter_r and label else 0.0
            objects.append((round(x + jx), round(y + jy), round(t)))
            t += gap_ms
        if label:
            blocks.append({"shape": label[0], "dir": label[1],
                           "t0": round(t0), "t1": round(t - gap_ms)})
        last = points[-1]

    def make_block(builder, kwargs):
        kwargs = dict(kwargs)
        floor = {"line": 5, "zigzag": 6, "arc": 5}.get(builder.__name__)
        while True:
            for _attempt in range(3000):
                pts, label = builder(rng, **kwargs)
                if _inside(pts):
                    return pts, label
            # too long for the playfield at this spacing: shorten, down to the
            # fewest notes the shape still needs
            n = kwargs.get("n", {"line": 7, "zigzag": 8, "arc": 7}.get(builder.__name__))
            if floor is None or n is None or n <= floor:
                raise RuntimeError(f"{builder.__name__} did not fit the playfield")
            kwargs["n"] = n - 1

    blocks_pts = [make_block(b, k) for b, k in plan]
    prev_pts = []
    for idx, (pts, label) in enumerate(blocks_pts + [(None, None)]):
        avoid = list(prev_pts) + (pts or [])
        for _try in range(30):
            filler, _ = junk(rng, junk_n, last, avoid=avoid)
            if len(filler) >= junk_n:
                break
        else:
            raise RuntimeError("could not place irregular filler between blocks")
        emit(filler, None)
        if pts is None:
            break
        emit(pts, label)
        prev_pts = pts
    return name, objects, blocks


def write(name, objects, blocks, gap_ms, note):
    OUT.mkdir(parents=True, exist_ok=True)
    lines = ["osu file format v14", "", "[General]", "AudioFilename: dummy.mp3",
             "AudioLeadIn: 0", "PreviewTime: -1", "Countdown: 0", "SampleSet: Soft",
             "StackLeniency: 0.0", "Mode: 0", "", "[Metadata]", f"Title:{name}",
             f"TitleUnicode:{name}", "Artist:synthetic", "ArtistUnicode:synthetic",
             "Creator:osu-critique", "Version:pattern", "", "[Difficulty]",
             f"HPDrainRate:5.0", f"CircleSize:{CS}", "OverallDifficulty:8.0",
             "ApproachRate:9.0", "SliderMultiplier:1.4", "SliderTickRate:1", "",
             "[TimingPoints]", f"0,{BEAT_MS:.6f},4,2,1,25,1,0", "", "[HitObjects]"]
    lines += [f"{x},{y},{t},1,0" for x, y, t in objects]
    (OUT / f"{name}.osu").write_text("\n".join(lines) + "\n")
    labels = {"map": name, "note": note, "gap_ms": gap_ms, "beat_ms": round(BEAT_MS, 3),
              "radius_px": RADIUS, "n_objects": len(objects), "blocks": blocks}
    (OUT / f"{name}.labels.json").write_text(json.dumps(labels, indent=1) + "\n")


def circle_kw(side, cw):
    return {"side": min(side, 3.4), "cw": cw}


def shapes_plan(side):
    """One of every shape, both windings where winding means something."""
    return [
        (line, {"side": min(side, 3.2)}),
        (polygon, {"k": 3, "side": side, "cw": True}),
        (back_and_forth, {"side": side * 1.4}),
        (polygon, {"k": 4, "side": side, "cw": True}),
        (zigzag, {"side": side}),
        (star, {"side": side, "cw": True}),
        (polygon, {"k": 3, "side": side, "cw": False}),
        (circle, circle_kw(side, True)),
        (polygon, {"k": 5, "side": side, "cw": False}),
        (arc, {"side": min(side, 3.6), "cw": False,
               "turn_deg": 20.0 if side <= 3.4 else 40.0, "n": 7 if side <= 3.4 else 5}),
        (polygon, {"k": 6, "side": side, "cw": True}),
        (stack, {}),
        (polygon, {"k": 4, "side": side, "cw": False}),
        (line, {"side": min(side, 3.2)}),
        (circle, circle_kw(side, False)),
        (zigzag, {"side": side}),
        (polygon, {"k": 3, "side": side, "cw": True, "reps": 3}),
    ]


def main():
    half = BEAT_MS / 2          # 1/2 beats
    quarter = BEAT_MS / 4       # 1/4 beats
    specs = [
        ("geo_clean", 11, shapes_plan(3.2), half, 0.0,
         "every shape, exact coordinates, 1/2 spacing"),
        ("geo_sloppy", 12, shapes_plan(3.2), half, 0.28,
         "every shape, hand-placed jitter of ~0.28 radii"),
        ("geo_stream", 13, shapes_plan(2.2), quarter, 0.0,
         "every shape at stream tempo and tight spacing"),
        ("geo_wide", 14, shapes_plan(4.5), half, 0.15,
         "every shape at jump spacing, light jitter"),
        ("geo_junk", 15, [], half, 0.0, "irregular filler only: nothing may be labelled"),
    ]
    for name, seed, plan, gap, jit, note in specs:
        if name == "geo_junk":
            rng = random.Random(seed)
            pts, _ = junk(rng, 400, (FIELD[0] / 2, FIELD[1] / 2))
            objects = [(round(x), round(y), round(1000 + i * gap)) for i, (x, y) in enumerate(pts)]
            write(name, objects, [], gap, note)
            continue
        _, objects, blocks = build(name, seed, plan, gap, jit)
        write(name, objects, blocks, gap, note)
        print(f"{name}: {len(objects)} objects, {len(blocks)} labelled blocks")


if __name__ == "__main__":
    main()
