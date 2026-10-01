# Roadmap and handoff

For the next agent picking this up. Read this file, then `docs/profile.md` and
`docs/object_schema.md`. The vault note `~/.local/share/ryoku/rashin/memory/osu-critique-handoff.md`
holds the private half: the author's measured player profile and the reference
numbers each feature below should reproduce.

State: **0.3.1**, `main` = `81fef6c`, 58 tests green, CI on every push, tag →
wheel + GitHub release (`.github/workflows/release.yml`).

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
2. When the question is about the **hand** rather than the taps, stop using the
   metrics and re-derive from the frames: sample `cursor_at(t)` around each
   object and measure distance at the note instant, closest approach and when it
   happens, the along/lateral split, and the ceiling curve. `scripts/autopsy.py`
   does exactly this for one replay (numbers + two figures).
3. The **trust block is what makes the output usable.** It states the per-count
   deltas against the game and refuses to let an untrustworthy judgement read as
   fact. Keep that discipline: every new block should carry its own sample size
   and a population gate, and the reports should never state a rate from an
   n<10 bucket.
4. Every diagnosis of substance came from a **contrast**, not an absolute: same
   map across attempts; shapes with corners vs shapes with reversals; cursor
   arrival vs press timing. Prefer features that produce a contrast.

Two examples of what that way of working produced (both reproduced by
`scripts/autopsy.py`):

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
.venv/bin/python -m pytest -q                       # 58 tests, no network
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

### 1. Aim mode (highest value, ~1 session + a fixture)

**Why.** The tool cannot analyse a Relax replay at all today — its own trust note
says "aim data is meaningless" — and RX is the cleanest aim measurement there is,
because the game taps and only the cursor is left. It is also the missing half of
every normal replay's diagnosis.

**Spec.** A cursor-centric block that works with or without RX
(`metrics.aim_mode`, or a `--aim` section in the metrics):
`distance_at_note_r`, `closest_approach_r`, `peak_offset_ms`, `window_entry_ms`,
`reached_not_on_time_pct`, `along_r` / `lateral_r`, and the ceiling curve
(`distance_at_note_r` binned by required cursor speed) plus a 6-panel figure.
`scripts/autopsy.py` is the reference implementation — lift it into
`metrics/aim.py` + `charts.py` and make the CLI call it.

**Acceptance.** On the author's RX replay it reproduces (within rounding): 0.72 r
mean at the note, 0.26 r median closest approach, median peak +10 ms, 16.8 %
reached-not-on-time, ceiling 0.47 r at ≤1 px/ms rising to 1.19 r above 3 px/ms.
Add an RX fixture to `tests/fixtures/` (ask the author to export + anonymize one)
and a golden test over those numbers. Until then, test the helpers on synthetic
frames.

**Traps.** Do not derive aim from presses for RX (there are none, or they are
irrelevant). The replay may still be in map time (see the calibration section) —
convert before quoting ms. Keep `WINDOW_MS` (currently 320 ms) explicit in the
output so the "reached at all" claim is auditable.

### 2. Miss-autopsy block (~1 session)

**Why.** The shape-class table, arrival margin and per-leg path efficiency are
what produced every finding; they belong in the tool instead of in throwaway
scripts.

**Spec.** Per-play: 5-note window shape classes (`near-reversal chain` /
`cornered (box)` / `flow` / `mixed`) with n-gated non-300 rates; arrival-margin
distribution at press time; press-time vs arrival offset; per-leg heading error
and path efficiency; mid-travel "stutter" press share. Rendered as a report
section plus a worst-window gallery figure.

**Acceptance.** Reproduces the published tables for the author's MONTAGEM and
4ever replays: reversals 17.5 % / 9.1 % off-300 vs cornered 0 % / 0 %; the two
4ever misses at 0.98 r and 1.20 r short with presses +16 ms / −9 ms; per-leg
heading error 0–14°.

### 3. Slider bodies, ends and ticks (~2 sessions)

**Why.** 36–55 % of the objects on the author's maps are sliders, they are judged
by their head only, and that is almost certainly why trust fails on every
slider-heavy play (5–10 objects per play where the game says 100 and we say 300,
with the miss count exact). It also caps the accuracy of every per-family rate on
those maps.

**Spec.** Model the head + ticks + end (slider library exposes the curve, length,
repeat, duration; `slider`'s own `Replay.hits()` shows one strict implementation
to borrow from — it over-detects misses, so take its mechanics, not its
thresholds). Emit `slider_break` as a first-class result distinct from `miss`.

**Acceptance.** On the author's slider-heavy replays the 300/100 split stops
drifting by ~10 objects and `trust.within_tolerance` goes true where it should.

### 4. Tier 2a: cross-attempt structure (~1 session)

**Why.** The strongest signal available is the same structure across attempts
(the author has repeated plays of RASPUTIN, Passcode, overture), and the schema
already carries `beatmap_md5` for grouping. Cheap version: group the
`out/*_metrics.json` files by md5, aggregate family/shape rates, and report which
structures are stable weaknesses vs one-off noise. Full version adds a sqlite of
per-object rows — not needed until ~20–30 plays are analysed.

**Acceptance.** RASPUTIN 09-01 → 09-22 comparison reproduces: 1/2 jump buckets
roughly halve (25.3→13.3 %, 34.3→17.1 %) while 1/4 dense barely moves
(27.7→22.8 %).

### 5. Dual-window reporting when calibration overrides a mod flag (~2 hours)

**Why.** Some lazer exports store frames in map time while claiming DT (Bang
Bang, 4ever). The calibration then picks scale 1.0 and every ms in the metrics is
map time, which is a silent 1.5× factor for a reader. `profile.py` already
converts to the player's time base (`time_factor = mod_scale / scale`); the raw
metrics and the console do not.

**Spec.** Whenever `trust.scale_overridden`, report both: the calibrated windows
and the player-time windows, and label every ms column with which base it is in.

### 6. Stream detection by rhythm + velocity continuity (half a session)

**Why.** The detector is still "≥4 consecutive circles with ≤4r spacing". It
called 1/2 filler runs "streams" on Bang Bang (where the real speed material is
1/8 slider-jumps) and it is blind to slider-interleaved bursts. `profile.py`'s
`chains` (steady gap ≤ tolerance, any kind) is the better primitive — promote it
and add a velocity-continuity term (`spacing / dt` within ±40 % across the run).

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
