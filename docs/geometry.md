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

- Sliders are nodes by their **head** by default; a shape built from slider tails is
  invisible unless `slider_tails` is on (below). Segments touching a slider carry
  `has_sliders`.
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

## Slider tails (`classify(..., slider_tails=True)`, default **off**)

A slider's exit is where the cursor must be when it ends, so a shape can be drawn
through tails. With the flag on, `classify` runs the detectors over three views of
the map and keeps the longest candidate at each start (mixed first on ties):

- `mixed`: the historical view (head nodes, exit-to-head legs). Kept because
  zigzags on real maps need those legs; dropping it lost segments on a real map.
- `head`: head nodes, head-to-head legs. Fixes shapes whose heads are exact but whose
  slider bodies pad the exit-to-head legs (those legs fail the leg-ratio tests).
- `exit`: exit nodes, exit-to-exit legs.

Segments carry `nodes` when the flag is on and the map has sliders; a map with no
sliders is classified identically either way. Ground truth: `geo_tail*` (every note a
slider whose *tail* sits on the vertex, head 1.6-2.4 r away), `geo_head` (control),
`geo_tail_junk`.

Labelled set (`scripts/eval_patterns.py [--slider-tails|--no-slider-tails]`), found / blocks:

| map | off | on |
|---|---|---|
| geo_clean, geo_stream, geo_wide | 17/17 | 17/17 |
| geo_sloppy | 13/17 | 13/17 |
| geo_head | 11/17 | 17/17 |
| geo_tail | 0/17 | 17/17 |
| geo_tail_sloppy | 0/17 | 17/17 |
| geo_junk, geo_tail_junk | 0 false positives | 0 false positives |

The default stays off: the circle-only maps cannot move (the flag is a no-op without
sliders), so the only evidence for "on" is fixtures generated for this feature, and
there are no owner labels on slider-heavy real windows yet. On eight real maps (by
eye, no labels) coverage moved by 0 to +1.7 points with 0-2 boundary shifts per
map, mostly new 4-note `stack`s of exit positions. Flipping `SLIDER_TAILS_DEFAULT`
also changes `library` features, so it needs a `FEATURE_VERSION` bump and a re-baseline.

## Tempo (`metrics/rhythm.py`)

Shape says *where* the notes are; tempo says *how fast they come*. `rhythm.tag(objs, segs)`
(objs annotated) adds `tempo` (`stream` ≤160 ms median gap, `burst` ≤250 ms, else `jumps`),
`run_share` (fraction of the segment inside a `streams.find_runs` run) and a `label` such as
"spaced circle stream" or "triangle jumps". Runs come from the existing stream detector, so
there is still one detector. A segment counts as in-run at ≥80 %; spacing < 1 r is "dense",
≥ 2 r "spaced". On FREEDOM DiVE this turns 143 arc/circle segments into "spaced/tight arc/circle
stream", which is what the map is.
