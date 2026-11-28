# Next work

Written at the end of the geometry session so a fresh session (on a machine with the
osu! install and real replays) can pick it up cold. Read `docs/ROADMAP.md` and
`docs/geometry.md` first. Order matters: each step depends on the one before it.

## Where things stand

- **Done and pushed (branch `claude/abandoned-project-review-34zxan`):**
  - `metrics/geometry.py`: shapes of runs of notes (triangle, square, rectangle, quad,
    pentagon, hexagon, star, back-and-forth, zigzag, line, arc, circle, stack). Cycles +
    position fits, not corner angles. Unlabelled is a valid answer.
  - `metrics/rhythm.py`: tags each segment `stream` / `burst` / `jumps` and a label like
    "spaced circle stream". Reuses `streams.find_runs`; there is still one stream detector.
  - `library.extract` now writes a `geometry` block (`coverage`, `shapes`, `labels`) into
    `features_json`; `FEATURE_VERSION = 2`, so a `library scan` re-extracts everything.
  - Synthetic ground truth in `tests/fixtures/patterns/` (`scripts/make_pattern_fixtures.py`,
    scored by `scripts/eval_patterns.py`), real-map ids in `real_maps.json`
    (`scripts/fetch_real_maps.py DIR` downloads them; the charts are not committed).
- **Judged by the owner by eye:** renders of Galaxy Collapse [Calamity] and FREEDOM DiVE
  [Arles] look right (FD is mostly spaced streams, and now reads as such). Blue Zenith and
  Hitorigoto were rendered but not judged.
- **Not wired anywhere yet:** `patterns.bucket` still feeds `recommend.py`; the web, report,
  index and per-run object records do not know about geometry.

## 1. Judge the rest, tune the table (small, do first)

- Fetch the real maps, render the unjudged ones, look:
  `python scripts/fetch_real_maps.py /tmp/maps`
  `python scripts/render_patterns.py /tmp/maps/5892713.osu out.png --per-shape 3`
  (also 1693862, 3528080, 3783132, 5195256, 172611).
- Rhythm thresholds are unvalidated: `STREAM_MAX_GAP=160`, `SPACED_R=2.0`, `TOUCHING_R=1.0`
  in `rhythm.py`. FREEDOM DiVE has 105 "tight" and 38 "spaced" segments; check that split
  by eye. Also decide whether gap in ms or in beats is the right axis for "stream".
- Coverage is low on tech maps (8% Galaxy Collapse, ~20% Blue Zenith, 46% FD). That is
  fine as long as the labels it does give are right; do not loosen thresholds to raise it.
- Any change to the geometry table must keep `scripts/eval_patterns.py` clean (0 false
  positives on `geo_junk`, 0 missed on clean/stream/wide) and the multi-seed validation
  (held-out seeds 5000-5059 in the earlier session: 0 to 0.2 % failures, extreme jitter
  about 12 %). Re-run `pytest tests/test_geometry.py`.

## 2. Replace the recommender's map side (the big one)

Owner's view: "recommended/improvers should use someone else's algorithm, I doubt I can make
a better one." Keep the player side (miss-rate residuals from the owner's own replays); stop
inventing a map-difficulty description.

- Use rosu-pp attributes instead of home-made buckets: `Difficulty.calculate` gives aim,
  speed, flashlight, slider factor, speed-note count etc.; `.strains()` gives per-400 ms
  aim / aim_no_sliders / speed / flashlight (rhythm and reading are `None` for std in
  rosu-pp-py 4.0.2, so do not plan around them).
- The "material" dimensions in `recommend.py` should come from those plus the new geometry
  `labels` (for "what kind of patterns does this map have"). Drop `patterns.bucket` consumers
  in `library.py` / `recommend.py` once nothing reads them.
- DONE: improver / maintain validated on held-out runs; the improver gap cut-off and the
  maintain bucket were deleted (see `docs/recommend.md`). Do not reintroduce cut-offs without
  rerunning `scripts/validate_recommend.py`.
- Constraint from CLAUDE.md: `recommend --json` must stay byte-equal between calls. Bump
  `FEATURE_VERSION` again if the extracted features change. Update `docs/recommend.md`.

## 3. Put geometry on the replay side

The classifier is a map property; recommender weaknesses are per-run. To say "you miss
squares" the per-object records need the shape.

- `geometry.label_objects(objs, segs)` already sets `shape` / `shape_id` per object. Call it
  (and `rhythm.tag`) in `report.analyze` and store the labels in `out/<tag>_objects.json`.
- Then consolidate the three overlapping descriptions of "what the map is":
  `profile.family`, `profile` sequences/chains, `streams.find_runs`. Keep `find_runs` (it is
  the primitive); make family a view over geometry + tempo, or delete it.
- Add a per-shape miss-rate block to the metrics (population gate from CLAUDE.md:
  `min(20, max(8, 3% of objects))`, never a rate from n<10, always quote n). This needs
  the owner's real replays, which is why it is not done.
- New metric blocks need fixtures (`tests/fixtures/`) and a `FEATURE_VERSION` / index
  schema bump if they are indexed. The index is a projection; heavy per-object data stays
  in the JSON.

## 4. Fix the feed page

Critique from rendering it (see the earlier session; reproduce with `osu-critique serve`
and open `/feed`):

- Lead with a per-session summary instead of a flat list of runs.
- The `verdict` field exists in the data and is never rendered.
- The header contradicts itself.
- Export chatter (BeatmapExporter status lines) crowds out the plays; collapse it.
- Wording should go through `web/glossary.py` like the rest of the site.
- Do this after step 3, so the feed can say what shapes you struggled with.
- `app.js` is untested by the server suite: after editing, check the browser console.

## 5. Open questions and smaller items

- **Judge fidelity:** 2363 of 3462 exact (68.3 %) against the game's recorded counts after
  spinner rating (no-spinner 74.1 %, spinner 60.4 %). Open: the one-directional miss
  over-detection on long/miss-heavy plays, pauses (29 % exact), slider head/tail. Run
  `scripts/judge_drift.py` on real replays; this is the invariant everything else stands on. It needs the real replays (6 tests skip without them).
- **Slider-tail nodes:** built behind `classify(slider_tails=True)`, default off (PLAN phase C,
  `docs/geometry.md`). Open: label slider-heavy real windows, then decide the default
  (flipping it needs a `FEATURE_VERSION` bump).
- **Radial bursts / spokes:** notes fanning out from and back to one point. Not detected;
  currently falls out as unlabelled or as shuttle.
- **Geometry gaps:** no 3D-ish shapes (figure eights), no dynamic shapes whose size changes
  lap to lap (spirals, expanding squares). Each would be one more detector and one more
  generator block plus a ground-truth fixture.
- `geometry.PRIORITY` still lists "star"; "back_and_forth" now only comes from the period-2
  cycle. Harmless leftovers.

## Working agreement that paid off

Build the generator and ground truth first, then the detector, then **look at real maps and
let the owner judge**. The synthetic fixtures can only prove the classifier recovers what was
put in; only a human looking at renders can say the labels match what a player calls a
triangle. Do the same for anything new.
