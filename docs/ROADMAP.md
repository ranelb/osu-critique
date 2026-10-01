# Roadmap and handoff

For the next agent picking this up. Read this file, then `docs/profile.md` and
`docs/object_schema.md`. The vault note `~/.local/share/ryoku/rashin/memory/osu-critique-handoff.md`
holds the private half: the author's measured player profile and the reference
numbers each feature below should reproduce.

State: **0.9.0**, `main` = `81fef6c`, 126 tests green, CI on every push, tag →
wheel + GitHub release (`.github/workflows/release.yml`).

## Shipped since the handoff

- **0.4.0 — aim mode** (`metrics["aim_mode"]`, `docs/aim.md`): the cursor path is
  re-derived from the frames for every run — distance at the note, closest
  approach and when it peaks, the along/lateral split, reached-not-on-time and
  the speed-conditioned ceiling curve — with a six-panel figure
  (`out/<tag>_aim.png`) and `--no-aim` to skip it. Works with or without Relax,
  so a Relax replay is now analysable: the old note said "aim data is
  meaningless", which was only true of the press-time numbers.
  `scripts/autopsy.py` is now a thin printer over the library's blocks (plus the
  worst-arrival table), so its numbers cannot drift.
- **0.5.0 — miss autopsy** (`metrics["autopsy"]`, `docs/autopsy.md`): 5-note shape
  classes with n-gated off-300 rates, the press-time arrival margin, press vs
  arrival timing, per-leg heading error and path efficiency, mid-travel
  ("stutter") press share, and each miss with its own press and geometry; plus the
  worst-stretch gallery (`out/<tag>_windows.png`) and `--no-autopsy` to skip it.
- **0.6.0 — slider bodies and the edge guard** (`metrics.sliders`, the `slider_*`
  record fields, `assignment.EDGE_GUARD_MS`): every slider's curve/ticks/tail are
  measured, and the judgement windows gained the empirical 1 ms guard that makes
  the 300/100 split agree with the game (14 plays exactly, total drift halved).
- **0.7.0 — cross-attempt structure** (`attempts`, `metrics/attempts.py`):
  metrics files grouped by `beatmap_md5` and ordered by the replay's `played_at`,
  comparing family and shape rates across attempts into consistent weaknesses vs
  swing ("one-off") buckets. New metrics fields `played_at` / `replay_md5` make
  the grouping and de-duplication possible.
- **0.8.0 — two clocks, labelled** (`metrics.time_base`): when a replay's mod
  flag and its frames disagree, the player-time windows are reported beside the
  frames' ones and both readers say which base every ms is in.

---

## The most useful thing about this tool

**The value is not the verdicts, it is that the per-object record plus the raw
cursor frames let you ask what the hand actually did — and every real question
so far has been answered that way, not by the built-in metrics.**

Concretely, in order of leverage:

1. `out/<tag>_objects.json` (the frozen schema) is the spine. One row per
   object: time, position, `result`, `error_ms`, `aim_r`, `cursor_speed`,
   `spacing_r`, `snap` (in **quarter-beats**), `bpm_eff`, `angle_deg`,
   `strain_aim`, `strain_speed`. Bucket it and you can answer almost anything
   without touching the replay again.
2. When the question is about the **hand** rather than the taps, the two
   re-derivation blocks are now computed for every run: the cursor arrival
   (`metrics.aim_mode`, docs/aim.md) and the miss autopsy (`metrics.autopsy`,
   docs/autopsy.md — shape classes, arrival margin, press vs arrival, legs,
   stutter, the misses themselves). Re-derive from the frames for anything they do
   not cover; `scripts/autopsy.py` prints both for one replay, with the figures.
3. The **trust block is what makes the output usable.** It states the per-count
   deltas against the game and refuses to let an untrustworthy judgement read as
   fact. Keep that discipline: every new block should carry its own sample size
   and a population gate, and the reports should never state a rate from an
   n<10 bucket.
4. Every diagnosis of substance came from a **contrast**, not an absolute: same
   map across attempts; shapes with corners vs shapes with reversals; cursor
   arrival vs press timing. Prefer features that produce a contrast.

Two examples of what that way of working produced (both reproduced by
`metrics.aim_mode` + `metrics.autopsy`):

- Three replays had misses at press-time aim of 1.07–1.45 r. The frames showed
  the cursor's *closest approach* was 0.26–0.4 r (fine) but that it peaked
  ~10 ms **after** the note, while the player's taps are 3–9 ms **early** — the
  two biases conspire, and the press lands while the cursor is still travelling.
  Not reading, not flicks: arrival timing.
- The same replay family shows the failure is confined to **near-reversal chains**
  (5-note windows with ≥2 turns >120°, 82–91 % of those maps' objects) while
  cornered/box windows are 0 % off-300 — which retires the "I can't read
  rectangles" hypothesis with data instead of opinion.

---

## Working method

```sh
cd ~/Projects/code/osu-critique
.venv/bin/python -m pytest -q                       # 126 tests, no network
.venv/bin/osu-critique analyze <replay.osr> <map.osu> tag --charts
.venv/bin/osu-critique report out/tag_metrics.json  # deterministic critique
.venv/bin/python scripts/autopsy.py <replay.osr> --tag tag --out out/autopsy
```

Read `metrics["trust"]` first, always. Replays and maps are auto-paired by
beatmap MD5 (lazer exports + its content-addressed store, stable on Windows, or
`replays/` + `maps/` in the repo). Real replays are the author's: never commit an
unanonymized `.osr` (`scripts/make_synthetic_fixtures.py --anonymize` exists),
and keep personal coaching numbers in the vault, not in the public repo.

---

## Backlog, in the order I would do it

### 1. Aim mode — ✅ shipped in 0.4.0 (`docs/aim.md`, `metrics.aim`)

**Why.** The tool could not analyse a Relax replay at all — its own trust note
said "aim data is meaningless" — and RX is the cleanest aim measurement there
is, because the game taps and only the cursor is left. It is also the missing
half of every normal replay's diagnosis.

**Spec.** A cursor-centric block that works with or without RX
(`metrics.aim_mode`, or `--no-aim` to skip): `distance_at_note_r`,
`closest_approach_r`, `peak_offset_ms`, `window_entry_ms`,
`reached_not_on_time`, `along_r` / `lateral_r`, and the ceiling curve plus a
6-panel figure. `scripts/autopsy.py` was the reference implementation; it now
calls the library instead of duplicating the maths.

**Acceptance.** Met: on the author's RX replay the block reproduces 0.72 r mean
at the note, 0.26 r median closest approach, median peak +10 ms, 16.8 %
reached-not-on-time, ceiling 0.47 r at ≤1 px/ms rising to 1.19 r above
3 px/ms. `tests/test_aim.py` pins a synthetic RX fixture (`synth_rx`) with a
known cursor path exactly and checks these numbers when `OSU_TEST_RX_REPLAY` /
`OSU_TEST_RX_MAP` are set (the replay itself is the author's, not committed).

**Traps (learned).** Do not derive aim from presses for RX. Convert ms to the
player time base before quoting (the block inherits the calibrated rows). Keep
`window_ms` explicit in the output. Row indices are *object* indices — the old
autopsy indexed its non-spinner rows by object index, which silently mis-mapped
every object after the first spinner; the shape/worst tables were off until
this shipped as a dict keyed by object index.

### 2. Miss-autopsy block — ✅ shipped in 0.5.0 (`docs/autopsy.md`, `metrics.autopsy`)

**Why.** The shape-class table, arrival margin and per-leg path efficiency are
what produced every finding; they belong in the tool instead of in throwaway
scripts.

**Spec.** Per-play: 5-note window shape classes (`near-reversal chain` /
`cornered (box)` / `flow` / `mixed`) with n-gated non-300 rates; arrival-margin
distribution at press time; press-time vs arrival offset; per-leg heading error
and path efficiency; mid-travel "stutter" press share; plus a report section and
the worst-window gallery figure (`out/<tag>_windows.png`).

**Acceptance.** Met: MONTAGEM reversals 17.5 % off-300 (n=143) vs cornered 0 %
(n=14), 4ever 9.1 % (n=165) vs 0 % (n=9); the 4ever misses at 1.20 r (press
−9 ms, aim 1.26 r) and 0.98 r (press +16 ms, aim 1.07 r) and MONTAGEM's three at
1.32/1.30/1.07 r (presses +5/+2/−3 ms); per-leg heading error median 2-3°, p90
6-8°, max 14° — no reading problem. `tests/test_autopsy.py` pins the helpers on
synthetic frames and checks these numbers when the replays are pointed at with
`OSU_TEST_MONTAGEM_*` / `OSU_TEST_4EVER_*`.

**Traps (learned).** Legs shorter than ~1.5 circle radii have no meaningful
direction (including them produced a 117° "heading error" on a leg where the
cursor moved 2 px) — filter on the object gap *in radii*, not pixels. The turn
list was also reading `objs[-1]` for the `i == 2` window (the last object of the
map); guard `k - 2 >= 0`.

### 3. Slider bodies, ends and ticks — ✅ shipped in 0.6.0 (`metrics.sliders`, edge guard)

**Why.** 36–55 % of the objects on the author's maps are sliders, judged by their
head only, and the 300/100 split drifted on the slider-heavy plays (5–22 objects
per play with the miss count exact).

**Spec.** Model the head + ticks + end (`slider` exposes the curve, length,
repeat, duration and `true_tick_points`; its `Replay.hits()` is one strict
implementation to borrow mechanics from). Emit `slider_break` as a first-class
result distinct from `miss`.

**Acceptance.** Met, but by a *different* mechanism than the plan assumed — see
below. On `MONTAGEM BATCHI` and `4ever` the 300/100 split now matches the game
exactly (`trust.within_tolerance` true); across the 55 stored replays the judged
counts reproduce 14 plays exactly and the total weighted L1 fell from 1943 to
1470.

**What actually fixed the drift (measured, not assumed).** It was not the body —
it was a **1 ms edge guard** on the hit windows (`assignment.EDGE_GUARD_MS`).
A replay's frame clock is floored to the millisecond, so a stored press time can
be up to 1 ms earlier than the time the game judged: an error measured at the
window edge belongs to a press the game saw outside it. Ranking the candidate
rules by total drift over all 55 replays: no guard 1943 L1 / 1 exact play, 0.5 ms
1640 / 8, **1.0 ms 1470 / 14**, 1.5 ms 1998 / 6. Slider bodies were the wrong
suspect: the excess 300s were objects sitting within ~1 ms of the window edge,
circles included.

**The slider body is measured, not judged.** `metrics/sliders` follows every
slider's curve (repeats folded back), its ticks (`true_tick_points`) and its tail,
and records `slider_tail_off` / `slider_missed_ticks` / `slider_off_pct` per
object. Using that to degrade a slider whose tail was dropped (the plan's
`slider_break`) was tested and **rejected**: over 19 slider-heavy replays it makes
15 worse and 1 better (L1 729 -> 920), because the cursor is *allowed* to cut the
body — RASPUTIN alone has 179 cut sliders and 21 "dropped tails" on a play whose
counts match the game exactly. So the fields are descriptive (coaching: "you cut
25 % of sliders on 4ever"), and the judgement stays head-based. A small residual
miss drift remains on a few plays (FOOL MOON 66 vs 55, Hot N Cold 48 vs 42) and
those stay `trustworthy: false`.

### 4. Tier 2a: cross-attempt structure — ✅ shipped in 0.7.0 (`attempts`)

**Why.** The strongest signal available is the same structure across attempts
(RASPUTIN, Passcode, overture, Domino are all repeated), and the schema already
carried `beatmap_md5` for grouping.

**Spec / what shipped.** `osu-critique attempts [dir|file]` groups the metrics
files by beatmap md5, orders the attempts by the replay's `played_at` (a new
metrics field, with `replay_md5` for de-duplicating re-exports of one play),
drops nothing silently, and compares family and shape rates across attempts:

- **consistent weakness** — worse than the play's own off-300 rate in *every*
  attempt by ≥1.5×, from buckets that are populated everywhere (an adaptive gate,
  min(20, max(10, 3 % of the objects)), so a 150-object map is read from
  10-object buckets and a 1000-object one from 20-object buckets);
- **swings** — the rate moves ≥10 points between attempts, i.e. one-off or
  session noise until explained, *not* a stable weakness;
- plus `--json` for the whole block, and `report <dir>` now points at it.

**Acceptance.** The qualitative claim reproduces on RASPUTIN 09-01 → 09-22 (the
duplicate 09-22 export is de-duplicated): `slider_1/2_jump` 29.3 % → 12.8 % and
`slider_1/2_spaced` 43.0 % → 17.5 % (both roughly halve) while `slider_1/4_dense`
22.8 % → 26.1 % (moves by 3 points — "barely moves"). The published figures
(25.3→13.3, 34.3→17.1, 27.7→22.8) predate the 1 ms edge guard and the profile's
current family bucketing, so the test pins today's numbers *and* the shape of the
change.

**Not done (deliberately).** The full version — a sqlite of per-object rows — is
not needed at 22 stored runs over 9 repeated maps; the metrics files carry the
family and shape rates already. Revisit when a single map has ~20-30 plays.

### 5. Dual-window reporting when calibration overrides a mod flag — ✅ shipped in 0.8.0

**Why.** Some exports store frames in one clock while the mod flag claims another
(Bang Bang, 4ever, Domino). Calibration then keeps the frames' scale and every ms
in the metrics is that base — a silent 1.5x for a reader who believes the flag.
`profile.py` already converted (`time_factor = mod_scale / scale`); the raw
metrics and the console did not.

**Spec / what shipped.** `metrics["time_base"]` is emitted on every run:
`overridden`, `rows_scale`, `player_scale`, `rows_to_player`, `windows_ms_player`
and a `note` in words (None when the flag holds). `windows_ms` stays the frames'
base. The console summary prints the note and appends the felt window to the
timing line; the deterministic report prints it as a `TIME BASE:` line; both label
the map profile as `(player time)`; the coach prompt has a time-base bullet
warning against comparing ms across bases.

**The invariant that makes it real** (and the test that pins it):
``windows_ms_player == od_windows(od, mod_scale)`` — the second base is exactly
the windows of the mod the replay *claims*, multiplied through. On Domino (DT
claimed, frames in map time) the 300-window is 29 ms of frames = 19 ms of real
play, both present; on a play whose flag holds, nothing is printed at all.

**Cost note.** Scoped "~2 hours" in the first pass; it took ~3 minutes of work,
because the conversion already existed in `profile.py` and the Domino fixture
already triggered the case. The estimates in this file are session budgets, not
measurements — the expensive part of an item is the diagnosis, and this one had
none.

### 6. Stream detection by rhythm + velocity continuity — ✅ shipped in 0.9.0

**Why.** The detector was still "≥4 consecutive circles with ≤4r spacing" —
*spacing* standing in for speed. It called 1/2 filler runs streams on Bang Bang
and was blind to slider-interleaved bursts: **0 segments on MONTAGEM**, whose
runs are rhythmically tight (115 ms) but ~6r wide.

**Spec / what shipped.** `metrics.streams.find_runs` is now the shared primitive:
consecutive objects with a steady gap (within ±35 % of the running gap,
≤250 ms — the rule ``profile._chains`` already used) and a steady required cursor
speed (`spacing/dt` within ±40 % of the run's median), **any object kind**;
spinners break a run. `profile._chains` calls the same function with the velocity
term off, so the profile's numbers are unchanged (verified run-for-run on six
replays). `stream_stats` returns, per run: t_start/t_end, n, miss, mean/std err,
alt_ratio, key_pattern — plus what the material *was*: `gap_ms`, `notes_per_s`,
`velocity_r_ms`, `kinds`. `metrics.streams` also carries the aggregate
(`notes`, `misses`, gap and speed percentiles, kind mix); the report, console and
coach prompt quote the rate and the material instead of the word "streams".

**Measured effect** (old → new segments/notes): MONTAGEM 0 → 19/100, 4ever
0 → 12/59, Bang Bang 22 → 33/166, RASPUTIN 39 → 69/520, down 87 → 134/843. The
misfire it retires is pinned by a test: steady 100 ms gaps with spacing swinging
1r ↔ 3.9r (a 4x speed swing at constant rhythm) — the old rule called it a
stream, the new one does not.

### 7. Optional / later

- **`client.realm` ground truth**: lazer persists per-object hit events for local
  scores. A 1-hour spike decides whether that removes the inverse-judgement
  problem for lazer plays entirely (map-time/HR/relax quirks included). Do it
  before investing more in the judge if it works.
- **Percentile baselines**: replace any frozen baseline string with a rolling,
  difficulty-normalised percentile over stored runs (needs item 4's storage).
- **Family taxonomy depth**: only after items 1–3; taxonomy richness over an
  unvalidated judge is confident nonsense.

---

## Traps and environment quirks (learned the hard way)

- **`snap` is in quarter-beats**, so the osu! divisor is `4 / snap`. Labelling
  snap 8 as "1/8" is wrong (it is 2 beats) and that mistake produced three
  analyses of nonsense before it was caught. `profile.divisor()`/`beats_label()`
  are the correct implementations; always print the real ms gap next to a label.
- **Calibration** tries `[mod_scale, 1.0]` and keeps the lower weighted L1 over
  the whole count vector (`2·|Δmiss| + |Δ100| + |Δ50| + 0.5·|Δ300|`). Row times
  come out in *calibrated* time; the player's base is `mod_scale / scale`.
- **Sliders**: `pixel_length` is missing on some parsed sliders — fall back to
  `length` (fixed in 0.3.1, keep the fallback).
- **Row keys differ by layer**: pipeline rows use `error` / `aim` / `end`;
  written records rename them to `error_ms` / `aim_px` / `end_t`. `profile.py`
  has tolerant accessors (`hit_error`, `aim_px`, `end_time`) — reuse them.
- **The judgement is measured, not argued**: `scripts/judge_drift.py` reports
  the drift against the game's recorded counts over every replay it can pair
  (55 on the author's box) and can sweep alternative rules. Change `classify()`
  or the calibration only with that number in hand — the guard sweep is how the
  1 ms edge guard was chosen (1470 L1 / 14 exact, vs 1943 / 1 with no guard).
- **Population gates** must scale down on short maps: `min(20, max(8, 3 % of
  objects))`. A fixed 20 hid the real target on a 174-object map.
- **Never conclude from n<10**, and quote n with every rate.
- **git**: no global identity here — commits *and* annotated tags need
  `-c user.name=ran -c user.email=id+ranelb@users.noreply.github.com`.
  Push to `main`; the release workflow runs on tags.
- **`Developer.shell` inside `execute_typescript` loses stdout** in this
  environment; use the standalone shell tool for output-critical commands.
- **Fixtures**: `tests/fixtures/` holds the author's anonymized replays and
  synthetic edge cases. New features need new fixtures — ask for an export +
  anonymize; do not commit unanonymized replays, and do not put personal
  coaching numbers in the public repo.
