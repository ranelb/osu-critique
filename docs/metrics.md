# Per-play metrics

Everything `osu-critique analyze` writes into `out/<tag>_metrics.json`, alongside
the trust block and the per-object records (schema: [`object_schema.md`](object_schema.md)).

## Output files

`analyze` writes `out/<tag>_metrics.json` (this catalogue) and
`out/<tag>_objects.json` (one record per hit object — skip it with `--no-objects`).
With `--charts` it adds `out/<tag>_charts.png` (four panels: hit-error histogram,
error over time, spatial result map, aim-error histogram), `out/<tag>_aim.png`
(six cursor-arrival panels) and `out/<tag>_windows.png` (the worst arrival
stretches). The cursor-arrival and miss-autopsy blocks are computed for every run;
skip them with `--no-aim` / `--no-autopsy`.

Per-play metrics include:

- **Timing**: mean hit error (early/late bias), std → UR, distribution percentiles
- **Aim**: cursor distance from object centre at press time (in circle radii),
  per screen region
- **Aim (cursor arrival)**: the cursor path itself — distance at the note
  instant, closest approach within ±320 ms and when it peaks, the share reached
  but not on time, the along/lateral split, and the ceiling curve (distance at
  the note against the cursor speed the jump demands). Works with or without
  Relax ([aim.md](aim.md))
- **Miss autopsy**: the shape classes (5-note windows: near-reversal chain /
  cornered box / flow / mixed) with n-gated off-300 rates, the press-time arrival
  margin, press vs arrival timing, per-leg heading error and path efficiency,
  mid-travel "stutter" presses, and each miss with its own press and geometry
  ([autopsy.md](autopsy.md))
- **Slider bodies**: the curve (repeats included), ticks and tail of every
  slider — how much of each body the cursor actually traced, how many ticks it
  missed, and whether the tail was dropped (`metrics.sliders` and the
  `slider_*` fields in the per-object records)
- **Two clocks, labelled**: when a replay's mod flag and its frames disagree (a
  DT export stored in map time), `metrics.time_base` carries both — the frames'
  base that every ms is in, and the player's (`windows_ms_player`) — and the
  console summary and report say which is which, instead of quoting a silent
  1.5x
- **Rolling baselines**: the report compares a run against your stored runs
  (difficulty-normalised: UR as a share of the 300-window, misses per 100 objects,
  aim at one required-speed band) and says "better than 87 % of 21 runs" instead
  of only quoting a frozen threshold
- **Cross-attempt structure** (`attempts`): metrics files grouped by beatmap md5
  and ordered by `played_at`, comparing family and shape rates across attempts —
  which weaknesses are worse than the play itself *every* time, and which just
  swing between sessions
- **Patterns**: miss rates by spacing bucket — dense (≤2r), stream (2–4r),
  jump (4–7r), bigjump (>7r)
- **Streams**: runs of sustained notes found by **rhythm and velocity
  continuity** (steady gap ≤250 ms, required speed `spacing/dt` steady within
  40 %, any object kind — the old "≥4 circles at ≤4r spacing" rule used spacing
  as a proxy for speed and missed MONTAGEM's slider-interleaved bursts entirely:
  0 segments before, 19 now). Each run reports what the material was — median
  gap, notes/s, required speed, circle/slider mix — plus per-segment timing
  (std/UR) and alternation ratio (same-finger double-taps under pressure)
- **Tapping**: alternation ratio, same-key adjacencies, key balance, whiffed
  presses (taps that hit nothing — the rushing signal)
- **Sections**: quarter-by-quarter miss/error breakdown (fatigue detection)
- **Whiffs by cause**: every unused press explained — mash, off-target (the
  cursor was not on the circle), beside a slider head, duplicate, or after the map
- **Aim ceiling**: aim error (circle radii) fitted against cursor speed, with the
  slowest-to-fastest quartile means — a static "0.30-0.45r is good" hides the slope
- **Map profile**: the map's own character — effective BPM and real note gaps,
  pattern families (`kind_divisor_spacing`) with n-gated hit rates, slider
  character (path length and the cursor speed demanded), stamina (notes/s,
  longest sustained run, breaks), chains with hit rate by position, and
  signed bias per family ([profile.md](profile.md))
- **Trust**: per-count deltas against the game's own recorded hits, the scale the
  calibration chose, and whether the judgement can be trusted at all
- **Flags**: `failed_play`, `map_version_mismatch`, mods

## See also

- [`aim.md`](aim.md) — the cursor-arrival block in full.
- [`autopsy.md`](autopsy.md) — the miss autopsy in full.
- [`profile.md`](profile.md) — the map profile in full.
- [`trust.md`](trust.md) — how much to trust the judgement.
- [`object_schema.md`](object_schema.md) — the per-object record schema.
