# Roadmap

For contributors picking this up. Read this file, then `docs/profile.md` and
`docs/object_schema.md`. It records the decisions already made, the items still
open, and the traps that have bitten.

State: **0.25.1** (tag `v0.25.1` is the last published release); 353 tests green
(242 run anywhere: 52 need the `[web]` extra, 6 need real replays), CI on Python
3.10/3.12/3.14 on every push, tag → wheel + GitHub release
(`.github/workflows/release.yml`).

## The web UI arc — shipped (0.12.0 → 0.20.0)

A local FastAPI frontend over this library (optional extra `[web]`), a
**derived** SQLite index of runs (the JSON artifacts stay canonical and the DB is
rebuildable), map showcase pages in the osu! beatmap-listing idiom with covers
from `assets.ppy.sh`, human annotations in map time that the coach prompt reads,
stored LLM critiques with staleness hashes, an opt-in export and a deterministic
digest with a real feed, and per-run near-miss boards.

Where each piece lives: `docs/index.md` (the projection), `docs/web.md` (pages,
routes, boards), `docs/annotations.md`, `docs/ask.md`, `docs/export.md`
(export, digest, feed).

**Not now, deliberately** — the fence, so scope cannot quietly grow: replay
playback / cursor animation, auth or multi-user, public hosting, re-analysis
from the browser, global osu! leaderboards, a mobile-specific layout, and
websockets. Playback is the likely next one; the index stores
`replay_path`/`map_path` and a `/run/{id}/frames` route is reserved so adding
it does not need a schema change.

## Shipped since 0.12.0

- **0.24.x — critique tab refinements.** The size threshold warns instead of
  blocking; list pickers load 40 rows at a time on scroll; the mod filter covers
  maps and ranges only; the LLM answer sits above the deterministic summary; each
  replay row carries a dimmed beatmap cover. Static assets are content-fingerprinted
  after an edited `app.js` was served from cache and looked like broken JavaScript.
- **0.23.0 — the critique tab.** Select replays, whole maps and date ranges into
  one additive, deduplicated selection; the page builds **one deterministic text**
  and that text is the model's entire input. Up to 10 runs get full per-replay
  reports, above that it degrades to overview + per-map table + per-run table +
  cross-attempt stability, and the header counts what was left out. Stored at
  `out/critiques/scope/<hash>.json` (now `out/answers/<hash>.json`), hashed over text + prompt, with the text
  inside. `index.sqlite` mirrors metadata only.
- **0.22.x — decluttering.** A left rail and five folds; the run page dropped
  from 7.5 screens with 715 numbers to 1.9 screens and 206 words with everything
  folded. Peeks state the rule and the count, never a number the cards already
  show. Also fixed a dead-JavaScript regression: an edit sliced `initAnnotations`
  and `initBoards` out of `app.js`, so the page rendered while the playhead,
  boards and critique stream were silently dead.
- **0.21.x — the deterministic report as data.** `report_sections.py` builds
  typed items (`kv`, `note` with a tone, `table`) and `render_report()` renders
  them, so the CLI and the run page cannot drift. Found and fixed a latent crash
  on runs that store `legs: null`, an empty `error_shape` or null stream
  velocities; it now degrades per field.
- **0.20.x — the feed as a page, and per-run near-miss boards.** Every digest is
  written twice (`…md` canonical, `…json` structured); `/feed` renders the JSON.
  `web/boards.py` ranks misses by closest approach and the browser draws zoomed
  boards, a playfield-wide miss overview and the cleanest stretch. The digest now
  runs export first when enabled, and tracks three markers: `.ingest` (newest
  exported-file mtime seen), `.window` (newest **play** actually reported) and
  `.last` (when the digest ran).
- **0.16.x — index keys on the artifact, not the cwd.** `json_path` and every
  other stored path are absolute. Running the CLI from the repo and the service
  from somewhere else used to index every artifact twice.
- **0.16.0 — export and the digest.** The opt-in `osu-critique export` drives
  BeatmapExporter (MIT, sha256-pinned, vendored in this project's releases for
  linux/win/mac, disabled until `export.enabled`). Its menu is text-driven
  (`status …` / `reset`); the filter is **reset** when no status is configured,
  which is the bug that had been hiding loved/graveyard plays.
- **0.15.0 — stored critiques.** One canonical sidecar per run at
  `out/critiques/<run_id>.json`, mirrored into the index. `run_hash` covers the
  metrics **plus the player's notes**; `prompt_hash` covers the system prompt; a
  different model is not staleness. The web streams the call as SSE; the key
  never leaves the server.
- **0.14.0 — annotations.** Notes scoped to a map or a run, optionally stamped
  in map time. Canonical sidecars at `out/annotations/<beatmap_md5>.json`;
  `coach`/`prompt` read them, `report` deliberately does not.
- **0.13.0 — the web read path.** FastAPI + Jinja2 + htmx as the optional
  `[web]` extra. Cover-card listing, map page, run page with the trust banner,
  hit-error chart and the deterministic report.
- **0.12.0 — the index.** A SQLite **projection** of `out/` at
  `out/index.sqlite` — one row per artifact plus a `beatmaps` row parsed from the
  `.osu`, with the `sr` / `pp` / `rank_status` caches joined on. `--rebuild`
  drops and re-reads, `--check` reports drift and writes nothing.
- **0.11.0 — breakdown, stars/pp, status.** The speed cliff, reversal × spacing
  buckets, miss cascades and the worst ramp (`metrics/breakdown.py`); rosu-pp
  star ratings and pp (`metrics/difficulty.py`, optional `[stars]` extra); the
  ranked / leaderboard-only / unranked split via osu! API v2
  (`io/status.py`). `batch` skips a bad replay instead of dying on it.
- **0.4.0 → 0.10.0** — aim mode, miss autopsy, slider bodies, cross-attempt
  structure, dual-window reporting, rhythm/velocity stream detection and rolling
  baselines. Details below.

---

## Backlog, in the order it was built

### 1. Aim mode — ✅ shipped in 0.4.0 (`docs/aim.md`, `metrics/aim`)

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

**Acceptance.** Met: on a Relax reference replay the block reproduces 0.72 r
mean at the note, 0.26 r median closest approach, median peak +10 ms, 16.8 %
reached-not-on-time, ceiling 0.47 r at ≤1 px/ms rising to 1.19 r above
3 px/ms. `tests/test_aim.py` pins a synthetic RX fixture (`synth_rx`) with a
known cursor path exactly and checks these numbers when
`OSU_TEST_RX_REPLAY` / `OSU_TEST_RX_MAP` are set.

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

**Acceptance.** Met on two reference replays: near-reversal chains are 17.5 %
off-300 (n=143) vs 0 % for cornered windows (n=14) on one, and 9.1 % (n=165) vs
0 % (n=9) on the other; per-leg heading error median 2-3°, p90 6-8°, max 14° —
no reading problem. `tests/test_autopsy.py` pins the helpers on synthetic frames
and checks these numbers when the reference replays are pointed at with the
`OSU_TEST_*_REPLAY` / `_MAP` variables.

**Traps (learned).** Legs shorter than ~1.5 circle radii have no meaningful
direction (including them produced a 117° "heading error" on a leg where the
cursor moved 2 px) — filter on the object gap *in radii*, not pixels. The turn
list was also reading `objs[-1]` for the `i == 2` window (the last object of the
map); guard `k - 2 >= 0`.

### 3. Slider bodies, ends and ticks — ✅ shipped in 0.6.0 (`metrics.sliders`, edge guard)

**Why.** A large share of the objects on slider-heavy maps are judged by their
head only, and the 300/100 split drifted on slider-heavy plays (5-22 objects per
play with the miss count exact).

**Spec.** Model the head + ticks + end (`slider` exposes the curve, length,
repeat, duration and `true_tick_points`; its `Replay.hits()` is one strict
implementation to borrow mechanics from). Emit `slider_break` as a first-class
result distinct from `miss`.

**What actually fixed the drift (measured, not assumed).** It was not the body —
it was a **1 ms edge guard** on the hit windows (`assignment.EDGE_GUARD_MS`).
A replay's frame clock is floored to the millisecond, so a stored press time can
be up to 1 ms earlier than the time the game judged: an error measured at the
window edge belongs to a press the game saw outside it. Ranking the candidate
rules by total drift over the reference corpus: no guard 1943 L1 / 1 exact play,
0.5 ms 1640 / 8, **1.0 ms 1470 / 14**, 1.5 ms 1998 / 6. Slider bodies were the
wrong suspect: the excess 300s were objects sitting within ~1 ms of the window
edge, circles included.

**The slider body is measured, not judged.** `metrics/sliders` follows every
slider's curve (repeats folded back), its ticks (`true_tick_points`) and its
tail, and records `slider_tail_off` / `slider_missed_ticks` / `slider_off_pct`
per object. Using that to degrade a slider whose tail was dropped (the plan's
`slider_break`) was tested and **rejected**: it made most slider-heavy replays
worse, because the cursor is *allowed* to cut the body. So the fields are
descriptive (coaching: "you cut 25 % of sliders on this map"), and the judgement
stays head-based. A small residual miss drift remains on a few plays and those
stay `trustworthy: false`.

### 4. Cross-attempt structure — ✅ shipped in 0.7.0 (`attempts`)

**Why.** The strongest signal available is the same structure across attempts
on one map, and the schema already carried `beatmap_md5` for grouping.

**Spec / what shipped.** `osu-critique attempts [dir|file]` groups the metrics
files by beatmap md5, orders the attempts by the replay's `played_at` (a metrics
field, with `replay_md5` for de-duplicating re-exports of one play), drops
nothing silently, and compares family and shape rates across attempts:

- **consistent weakness** — worse than the play's own off-300 rate in *every*
  attempt by ≥1.5×, from buckets that are populated everywhere (an adaptive gate,
  min(20, max(10, 3 % of the objects)), so a short map is read from
  10-object buckets and a long one from 20-object buckets);
- **swings** — the rate moves ≥10 points between attempts, i.e. one-off or
  session noise until explained, *not* a stable weakness;
- plus `--json` for the whole block, and `report <dir>` now points at it.

**Not done (deliberately).** The full version — a sqlite of per-object rows — is
not needed while corpora are small and the metrics files carry the family and
shape rates already. Revisit when a single map has ~20-30 plays.

### 5. Dual-window reporting when calibration overrides a mod flag — ✅ shipped in 0.8.0

**Why.** Some exports store frames in one clock while the mod flag claims another.
Calibration then keeps the frames' scale and every ms in the metrics is that
base — a silent 1.5x for a reader who believes the flag. `profile.py` already
converted (`time_factor = mod_scale / scale`); the raw metrics and the console
did not.

**Spec / what shipped.** `metrics["time_base"]` is emitted on every run:
`overridden`, `rows_scale`, `player_scale`, `rows_to_player`, `windows_ms_player`
and a `note` in words (None when the flag holds). `windows_ms` stays the frames'
base. The console summary prints the note and appends the felt window to the
timing line; the deterministic report prints it as a `TIME BASE:` line; both label
the map profile as `(player time)`; the coach prompt has a time-base bullet
warning against comparing ms across bases.

**The invariant that makes it real** (and the test that pins it):
``windows_ms_player == od_windows(od, mod_scale)`` — the second base is exactly
the windows of the mod the replay *claims*, multiplied through.

### 6. Stream detection by rhythm + velocity continuity — ✅ shipped in 0.9.0

**Why.** The detector was still "≥4 consecutive circles with ≤4r spacing" —
*spacing* standing in for speed. It called wide-but-tight 1/2 filler runs
streams and was blind to slider-interleaved bursts.

**Spec / what shipped.** `metrics.streams.find_runs` is now the shared primitive:
consecutive objects with a steady gap (within ±35 % of the running gap,
≤250 ms — the rule ``profile._chains`` already used) and a steady required cursor
speed (`spacing/dt` within ±40 % of the run's median), **any object kind**;
spinners break a run. `profile._chains` calls the same function with the velocity
term off, so the profile's numbers are unchanged. `stream_stats` returns, per run:
t_start/t_end, n, miss, mean/std err, alt_ratio, key_pattern — plus what the
material *was*: `gap_ms`, `notes_per_s`, `velocity_r_ms`, `kinds`. The report,
console and coach prompt quote the rate and the material instead of the word
"streams".

The misfire it retires is pinned by a test: steady 100 ms gaps with spacing
swinging 1r ↔ 3.9r (a 4x speed swing at constant rhythm) — the old rule called it
a stream, the new one does not.

### 7. Optional / later

**a. `client.realm` ground truth — SPIKE DONE (0.10.0), and the answer is no.**
The premise was "lazer persists per-object hit events for local scores". It does
not: `client.realm` contains **no `HitEvent` type at all** (no such string
anywhere; the schema stores `BeatmapInfo`, `Ruleset`, `TotalScore`, `MaxCombo`,
`Accuracy`, `Statistics`…). What it *does* hold, per local score, is a
**category-count map** of lazer's own hit results — e.g.
`{"none":0,"miss":12,"meh":0,"ok":44,"great":406,"large_tick_hit":15,`
`"ignore_hit":147,"slider_tail_hit":146}` — plus the **SHA-256 of the exported
`.osr`**, so a score *can* in principle be linked to a replay.

Two things kill it as a practical source:

1. **It is per category, not per object.** It could say "this play had 44 oks and
   146 slider tails", never *which* object was misjudged, so it cannot validate a
   per-object judgement — only the shape of the model.
2. **Extracting it needs a Realm Core reader.** A strings-level harvest cannot
   pair a stats map to its replay (the file's string order is table-based, not
   record-based), and the only Python package named `realm` on PyPI is an
   unrelated project. A real reader means the .NET Realm SDK or hand-walking the
   file's B-trees: a day's work for per-category data.

**Decision: stop here.** The residual miss drift (a handful of plays, reported by
`trust`) stays unexplained, and that is the honest state of the tool: the recorded
counts are the only per-play truth available. One thing the spike *did* confirm in
passing: `slider_tail_hit` exists as a first-class result type, separate from
great/ok/meh/miss, which is consistent with the head-only model item 3 shipped.

**b. Percentile baselines — ✅ shipped in 0.10.0** (`report --history`,
`metrics/baseline.py`). Three difficulty-normalised scalars with a rolling
percentile over the stored runs: `timing_spread` (UR as a % of the 300-window —
OD/DT-normalised), `miss_rate` (per 100 objects — length-normalised) and
`aim_at_demand` (mean distance at the note, pooled over the 0.5-2.0 px/ms required
speed band). The report prints "better than 87 % of 21 stored runs (median 63.6)"
instead of only "UR 150 (good)", and says so plainly when there are fewer than 8
comparable runs. The frozen thresholds stay as the fallback (and as an absolute
sanity check); `--no-history` turns the section off.

**c. Family taxonomy depth — not now.** With the judge validated and the
cross-attempt layer in place this is the last structural item, but nothing in the
data currently demands more taxonomy: the shape classes (item 2) plus
`kind_divisor_spacing` already separate the material, and every extra bucket
shrinks the n behind each rate. Revisit with a question, not a hunch.

---

## Known gaps in the critique tab

- The model's answer is rendered in a `<pre>`, markdown and all, because the
  project has no markdown renderer and adding a dependency for one panel was not
  worth it in this pass. The deterministic side is text on purpose; the answer is
  not, and it shows.
- No "lens" selector (per-run / map / diet / timeframe) — one scope prompt serves
  every selection, which works but blurs the wording for a one-replay critique.
- The pickers page 40 rows at a time; deeper paging than the current filter has
  no dedicated UI yet.

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
   re-derivation blocks are computed for every run: the cursor arrival
   (`metrics.aim_mode`, docs/aim.md) and the miss autopsy (`metrics.autopsy`,
   docs/autopsy.md — shape classes, arrival margin, press vs arrival, legs,
   stutter, the misses themselves). Re-derive from the frames for anything they
   do not cover; `scripts/autopsy.py` prints both for one replay, with figures.
3. The **trust block is what makes the output usable.** It states the per-count
   deltas against the game and refuses to let an untrustworthy judgement read as
   fact. Keep that discipline: every new block should carry its own sample size
   and a population gate, and the reports should never state a rate from an
   n<10 bucket.
4. Every diagnosis of substance comes from a **contrast**, not an absolute: same
   map across attempts; shapes with corners vs shapes with reversals; cursor
   arrival vs press timing. Prefer features that produce a contrast.

## Working method

```sh
.venv/bin/python -m pytest -q                       # full suite, no network
.venv/bin/osu-critique analyze <replay.osr> <map.osu> tag --charts
.venv/bin/osu-critique report out/tag_metrics.json  # deterministic critique
.venv/bin/python scripts/autopsy.py <replay.osr> --tag tag --out out/autopsy
```

Read `metrics["trust"]` first, always. Replays and maps are auto-paired by
beatmap MD5 (lazer exports + its content-addressed store, stable on Windows, or
`replays/` + `maps/` in the repo). Never commit an unanonymized `.osr`
(`scripts/make_synthetic_fixtures.py --anonymize` exists), and keep personal
coaching numbers out of the repo.

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
  the drift against the game's recorded counts over every replay it can pair and
  can sweep alternative rules. Change `classify()` or the calibration only with
  that number in hand — the guard sweep is how the 1 ms edge guard was chosen
  (1470 L1 / 14 exact, vs 1943 / 1 with no guard).
- **Population gates** must scale down on short maps: `min(20, max(8, 3 % of
  objects))`. A fixed 20 hid the real target on a short map.
- **Never conclude from n<10**, and quote n with every rate.
- **git**: push to `main`; the release workflow runs on tags.
- **Fixtures**: `tests/fixtures/` holds anonymized replays and synthetic edge
  cases. New features need new fixtures — ask for an export + anonymize; do not
  commit unanonymized replays, and do not put personal coaching numbers in the
  repo. `out/` (analysis JSON/PNG) and `tmp_maps/` (extracted `.osu`) hold real
  numbers; both are gitignored and must never be committed.
