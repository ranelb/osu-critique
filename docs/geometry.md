# Geometric patterns

`metrics/geometry.py` labels **runs of objects** by the shape their path draws:
`triangle`, `square`/`rectangle`/`quad`, `pentagon`, `hexagon`, `star`,
`back_and_forth`, `zigzag`, `circle`, `arc`, `line`, `stack`. It replaces nothing
yet: `patterns.bucket` (dense/stream/jump/bigjump) still feeds the library and the
recommender. This is the map-side description that will.

It is a property of the **map**. Nothing here reads a replay.

## How

Three detectors over `build_objects` rows, geometry in circle radii:

- **cycles** — positions repeat with period *p* (a b c a b c). p=1 stack, 2
  back-and-forth, 3 triangle, 4 square / rectangle / quad, 5–6 pentagon, hexagon,
  or a **star** when the corners turn more than 1.5× the regular 360/p. A cycle
  must come round **twice** (2p notes). Each vertex is averaged over its laps, so
  hand-placed noise shrinks with repetition.
- **fits** — a **line** is every note within 0.6 r of a straight run; an **arc**
  is every note within 0.6 r of one least-squares circle, **and not already
  explained by a line** (it must bend by more than the tolerance). Sweep ≥ 300°
  is a **circle**. Corner angles were tried first and rejected: 0.3 r of
  placement slop on a 3 r leg is ~10° of turn, more than an arc's step.
- **zigzag** — alternating corners (30–150°, within 30° of each other), legs within
  1.5×, at least 6 notes.

Segments are non-overlapping, left to right, longest candidate first, with a
3-note look-ahead so stray notes before a shape cannot eat its start. Notes no rule
explains stay unlabelled; `summarize` reports that share and it is **meant to be
large**. Every threshold sits in one table at the top of the module.

Winding: osu! has y pointing down, so `cw` is clockwise as drawn on the playfield.

## Known gaps

- Sliders are nodes by their **head** only; a shape built from slider tails is
  invisible. Segments touching a slider carry `has_sliders`.
- Radial bursts through a centre, drifting or rotating polygons, crosses.
- There is no rhythm layer yet (`rate_ms` and `beats` are reported per segment,
  but "stream" / "burst" / "jump section" are not segments).
- Real-map accuracy is judged by eye (`scripts/render_patterns.py`), not measured.

## Checking it

```sh
python scripts/make_pattern_fixtures.py     # regenerate tests/fixtures/patterns/ (deterministic)
python scripts/eval_patterns.py             # score against *.labels.json
python scripts/fetch_real_maps.py DIR       # ids in tests/fixtures/patterns/real_maps.json
python scripts/render_patterns.py DIR/ID.osu [OUT.png] [--per-shape N]
```

The generator writes maps whose patterns are known by construction plus **irregular
filler** that must stay unlabelled. Labels are `{shape, dir, t0, t1}` in map ms, the
same format a hand-labelled real map uses. Measured over 60 unseen seeds (1,020
blocks per condition): exact and light-jitter, tempo-stream and wide-spacing maps
read back with 0–0.2 % misses and no false positives; a deliberately extreme
jitter (σ 0.28 r per axis) loses ~13 %, mostly lines and circles.

## Tempo (`metrics/rhythm.py`)

Shape says *where* the notes are; tempo says *how fast they come*. `rhythm.tag(objs, segs)`
(objs annotated) adds `tempo` (`stream` ≤160 ms median gap, `burst` ≤250 ms, else `jumps`),
`run_share` (fraction of the segment inside a `streams.find_runs` run) and a `label` such as
"spaced circle stream" or "triangle jumps". Runs come from the existing stream detector, so
there is still one detector. A segment counts as in-run at ≥80 %; spacing < 1 r is "dense",
≥ 2 r "spaced". On FREEDOM DiVE this turns 143 arc/circle segments into "spaced/tight arc/circle
stream", which is what the map is.
