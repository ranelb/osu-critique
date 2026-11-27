# Dashboard, skill profile and map recommendations

Goal: the web frontend stops being a viewer and starts teaching. A configurable
home dashboard says what you are weak at, and recommends specific maps — from
the maps you already own — that train exactly that weakness.

Status: steps 1–4 shipped (see "Steps"). This file is now the record of the
design and of what is still wrong with it ("Open questions"); it is no longer a
to-do list.

## Decisions

**Routes.** `/` becomes the dashboard; the maps grid moves to `/maps` with its
filters/sort/pager intact; `/map/<md5>` renders for a library map with no
attempts (stub: metadata + features, no history); `/learn` is the glossary;
`/settings` is the settings page.

**Dashboard.** Mixed, ranked: form strip (30 d / 90 d), activity calendar,
accuracy + UR trend, skill profile (strengths/weaknesses with `n`), weak-spots
table, recommendations, recently played, what's new. Every block is a widget —
on/off, order, window (where a window applies). A `player` filter defaults to
the most frequent player in the loaded corpus (never hardcoded) and is visible
on the page. RX/AP runs never contribute tap-derived evidence.

**Settings.** One htmx POST per control into
`~/.config/osu-critique/dashboard.json` (0600, next to `config.json`, survives
deleting `out/`). Fields: `player`, ordered `widgets: [{id, on, window}]`,
`sr_stretch`, `n_cards`, `buckets`. Unknown widget ids are ignored, missing ones
defaulted, plus "reset to defaults". Read-only: resolved paths, bind address.
Keys are never writable from the web, by anyone, ever.

**Library index.** `osu-critique library scan [--rebuild] [--status]` is a
sibling of `index`, writing rebuildable `library_beatmaps` rows into
`out/index.sqlite`. Features come from parsing the `.osu` (measured: ~11 ms/map,
~1 min for the ~5.7k maps in the lazer store) plus rosu-pp for SR — `[stars]`
becomes required for the scan. Incremental by mtime; a stale scan is refreshed
explicitly with `library scan` (decided later: *not* at `serve` boot, a cold scan
is ~150 s). `--status` optionally enriches rank
status through the osu! API when credentials exist; without it, candidates
carry `status: unknown` and stay eligible.

Realm (`client.realm`) is **rejected** as a source: no Python reader exists
(Rust tool is v24-only, 15/23 columns, no difficulty calculation; the TS lib
died in 2022), Realm never carries stream/spacing/anti-flow features anyway, and
lazer-only data doesn't cover stable/`.osz`/folder sources. Accepted cost: an
orphaned blob from a deleted set still looks installed; the blacklist is the
escape hatch.

**Recommendation.** `recommend.py` + `osu-critique recommend [--limit] [--json]`
(the same scorer the web layer calls, so it is testable without a server).
Buckets, mutually exclusive, a map appears in at most one:

- **new** — never played; novelty term in the score.
- **improver** — played, latest attempt ≥3 pp of accuracy below the median of
  your runs in the same 0.25-SR band, or the latest attempt failed, n ≥ 2. The
  card carries the proof: *best here 97.2 % over 4 runs, similar-SR median
  96.1, last attempt 91.4 %*. Band median needs ≥5 runs to exist, else the map
  is ineligible rather than compared against noise.
- **maintain** — at or above band median, last played ≥30 days ago, SR inside
  the comfort band. Same 30 days as the dashboard window, so "stale" and "this
  month" cannot disagree.

Gates: osu!std only, drain 0:40–4:30, ≥120 objects, one difficulty per set per
day, blacklisted maps excluded, SR inside the band. Score = weakness weight ×
feature similarity to the weakness centroid × difficulty fit (peak at
comfortable SR + 0.3, hard ±1.0 band, exposed as a 0–1 "stretch" slider). No
weight sliders. Every card prints its own deterministic why-line; no model.

**Weaknesses.** Reuses `attempts` + `profile.primary_target`; no second scoring
brain. A weakness is a family/metric at ≥1.5× the corpus-weighted rate,
`n ≥ min(20, max(8, 3% of objects))`, stable across attempts, and **actionable**
(it maps to a map feature the scorer can filter on). Top 3, ranked, with `n`
and a confidence word. Nothing is claimed at n < 10. "Observed but not
trainable here" is a separate, non-actionable list. DT normalised via
`bpm_eff` / `time_scale` but flagged, never silently merged.

**Blacklist.** `out/blacklist.json` sidecar (authored, like annotations and
critiques; survives index rebuild), mirrored into the index: `maps: [md5]` plus
`sets: [set_id]`. Scope chosen on the click (difficulty by default, whole set
via a menu). Permanent — no snooze in v1. × on the recommendation card, the
`/maps` card and the map page, with undo, plus a manager list in settings.

**Teaching.** `web/glossary.py` is the single wording source — term, one-liner,
long explanation, "how it's computed", link into `docs/metrics.md`. Rendered at
`/learn` with anchors and used verbatim for tooltips and the recommendation
why-lines. ~15 terms (the ones the dashboard shows). No drills. The LLM stays a
button, never the default page.

## Steps

### 1. Library scan and features
`library scan` command, `library_beatmaps` table in `index.py`, per-map feature
extraction (SR via rosu-pp, BPM, length, AR/OD/CS/HP, object count, slider
ratio, stream density, spacing buckets, anti-flow share, stamina proxy, kiai
share), incremental by mtime, boot refresh when stale, `--status` enrichment,
synthetic `.osu` fixtures in `tests/fixtures/library/` from
`scripts/make_synthetic_fixtures.py`.
**Done when:** `library scan` indexes the local store (150 s cold, 0.6 s
no-op), feature assertions pass on the six synthetic fixtures, and deleting
`out/index.sqlite` loses nothing but time.

Shipped: `src/osu_critique/library.py`, `library_beatmaps` (index schema v7),
`osu-critique library scan`, `tests/fixtures/library/` + `tests/test_library.py`,
`docs/library.md`.

### 2. Skill profile, scoring, blacklist
`recommend.py`: player filter, weakness detection (rules above), the three
buckets, the gate set, the scorer, the deterministic why-line and the improver
proof line. `out/blacklist.json` + index mirror + CLI scope options.
`osu-critique recommend [--limit] [--json]`.
**Done when:** `recommend --json` is deterministic against a fixture corpus,
every card states its evidence, and blacklisting a map removes it from the next
call.

Shipped: `src/osu_critique/recommend.py`, `src/osu_critique/blacklist.py`,
`blacklist` table (index schema v8), `osu-critique recommend` /
`osu-critique blacklist add|rm|list`, `docs/recommend.md`,
`tests/test_recommend.py` (21 tests).

Decisions taken while building (both recorded in `docs/recommend.md`):
the outcome is the **miss rate, band-corrected against your own median in the
same half-star band** — raw accuracy gaps were 0.2–1.7 pp and mostly reflected
map difficulty, while band-corrected miss-rate gaps separate cleanly (1.1 pp
excess versus 0.15 pp, n≈600/side); and the three buckets are **interleaved**
in the output instead of sorted by one shared score scale.

### 3. Dashboard and settings
`/` dashboard with the widget catalogue, `/maps` for the grid (with the golden
structure test retargeted), `/settings` with `dashboard.json` persistence,
read-only paths/bind, reset. Rail and mobile behaviour follow `docs/web.md`
(320–430 px is supported, not degraded).
**Done when:** toggling/reordering widgets changes `/` after a reload, a
malformed settings file still renders the page, and `scripts/mobile_audit.mjs`
passes on `/`, `/maps`, `/settings`, `/learn`.

Carry-over from step 2: `index --rebuild` deletes `library_beatmaps` with the
rest of the file, and `_ensure_index` rebuilds on a schema mismatch. The
dashboard must show "library not scanned / scanned N days ago" instead of an
empty recommendation panel.

Shipped: `src/osu_critique/dashboard.py` (widget catalogue, settings file,
per-widget data), `/` dashboard + `/maps` + `/settings`, `POST /blacklist` and
`/blacklist/remove`, `templates/partials/dash/*.html` (one per widget),
`tests/test_dashboard.py` (21 tests). `docs/web.md` gained "The dashboard",
"Settings" and "Blacklist"; the settings page is a single form that redirects,
so it works without JavaScript. Verified at 320/360/390/430 px in Chromium:
no document-level horizontal scroll on `/`, `/maps`, `/settings`, `/feed`
(the five-link nav needed to wrap below 620 px). `scripts/mobile_audit.mjs`
itself could not run — Playwright is not installed in this checkout.

### 4. Teaching and polish
`/learn` glossary, tooltips wired from the cards, × affordances everywhere plus
the settings manager, docs updates (`docs/web.md`, `docs/ROADMAP.md`,
`README.md` route table), screenshots from the synthetic corpus.
**Done when:** every dashboard metric and every recommendation links to a
glossary anchor that exists, `pytest -q` is green including the `[web]` extra,
and `docs/web.md` describes only what the code does.

Shipped: `web/glossary.py` (20 terms, three groups, one-liner + long + how +
doc link), `/learn`, `partials/gloss.html` (`gloss`/`learn` macros with native
`title` tooltips), × on `/maps` cards and the map page (difficulty and whole
set, with unblock), `tests/test_dashboard.py` +7 tests. Anchor integrity is a
test, not a promise.

Not done, deliberately: commit-able screenshots from the synthetic corpus
(`docs/web.md`'s "0.20.0 polish" wish). `docs/img/*.webp` still come from the
owner's real corpus, and re-rendering them is its own job, not a code change.

### 5. Open in osu! (after the plan)
Not in the original plan. A recommendation or a map opens in osu!lazer:
`POST /open` takes the md5, the **server** builds `osu://b/<id>` from the index
and runs `gio open`. A client-side `osu://` link was tried and dropped
(Firefox-based browsers refuse unknown schemes, phones have no handler); raw
links stay on the map page only. Shipped in 0.28.x.

## Open questions

Accepted edges: orphaned `.osu` blobs count as installed (blacklist covers it),
and `scripts/mobile_audit.mjs` needs Playwright installed locally to run.

Known limits of the method, not yet addressed. None is a bug; each caps what
the recommender can honestly claim:

- **Per-object evidence is discarded.** `recommend.py` joins one scalar per run
  (miss rate) to whole-map aggregate shares (stream, jump, anti-flow, slider,
  sustained). The per-object rows, `autopsy` and `attempts` data say *where*
  in a map the misses happened; the recommender never sees that, so a miss on a
  single reversal in a stream map is booked against "stream share".
- **No uncertainty.** Weaknesses come from a median split with a fixed gap
  (≥0.5 pp) and ratio (≥1.5×) gate. There is no interval, permutation test or
  bootstrap, and repeated attempts on one map are treated as independent runs.
- **Selection bias.** Only maps the player chose to play and exported are in
  the evidence, and a failed play is truncated, so its miss rate is not
  comparable to a full clear.
- **Nothing about how the player works.** No session structure, retry
  behaviour, time between attempts, fatigue or learning curve. `attempts.py`
  compares attempts of one map but does not model progress over time.
- **Unvalidated against outcomes.** Nothing checks that playing a recommended
  map improves the weakness it was recommended for.

---

# Pattern classification: descriptors, measurement, replay join

Context: `metrics/geometry.py` (from branch `claude/abandoned-project-review-34zxan`, merged) names
shapes conservatively and leaves most objects unlabelled by design (Obsession 10 %, TWO DIMENSIONS 22 %,
soft rain 18 % coverage). Measured on those maps, the unlabelled legs are mostly wide snap jumps
(Obsession: 98 % of legs >= 3 r, 60 % > 6 r) or tight curvy stream (TWO DIMENSIONS: 412 legs of 1-3 r,
363 returning near the object two steps back). A shape name cannot describe either. `docs/NEXT.md` step 3
(replay-side join) needs a category for every object, not only the shaped ones.

Rule for all phases: no threshold change lands unless the labelled-set score (phase A) holds or improves.
The owner's judgement is ground truth; the classifier and I are not.

## Phase A. Measurement (first, because everything else tunes against it)
- Blind labelling tool (`scripts/label_sheet.py` -> `out/labeling/labeler.html`): ~60 windows from Obsession,
  TWO DIMENSIONS, soft rain, Thunder [Thunder]; the classifier's label is hidden; the owner picks a shape or
  "none" and optionally clicks the first/last object (the pattern length is itself a complaint: too many
  objects per pattern).
- Labels exported as JSON, converted to the `{shape, dir, t0, t1}` format `scripts/eval_patterns.py` already scores.
- Report per-shape precision/recall, "labelled when it should not be", "unlabelled when it should be".

## Phase B. Leg descriptors (covers every object)
- New `metrics/legs.py`: per leg (slider tail -> next head) jump distance bucket in radii (stack < 1,
  close 1-3, medium 3-6, wide > 6), snap vs flow (turn angle against the previous leg), tempo (ms gap and
  beats via the local uninherited timing point), then maximal runs of one class as segments
  ("wide snap jumps at 150 ms"). Deterministic, no I/O, thresholds in one table.
- Fixtures in `tests/fixtures/` with known buckets; cut-points confirmed by the owner before they are final.
- Wired to `FEATURE_VERSION` in phase E (the `classes` block).

## Phase C. Slider tails as nodes
- Cycle and fit nodes from exit-to-head legs (`end_x`/`end_y`) behind a flag; compare against the phase A
  score before enabling.
- **Status: built, flag off.** `geometry.classify(..., slider_tails=...)` / `SLIDER_TAILS_DEFAULT = False`;
  generator ground truth `geo_tail`, `geo_tail_sloppy`, `geo_head`, `geo_tail_junk` in
  `make_pattern_fixtures.py`. Score off vs on: circle-only maps identical (flag is a no-op without sliders),
  slider fixtures 0/17 -> 17/17 (tail), 11/17 -> 17/17 (head control), junk false positives 0 -> 0.
  Not enabled: the only evidence for "on" is fixtures made for it, and there are no owner labels on
  slider-heavy windows. Enabling also needs a `FEATURE_VERSION` bump. Numbers and views in `docs/geometry.md`.

## Phase D. Drifting polygons and curvy stream
- Turn-walk polygons (one lap of same-sign turns near 360 m / n, closure reported as a number, not a gate),
  per-polygon tolerance `min(22, 0.2 * ideal)` so a 45 deg ring is not a hexagon; wide-jump walks are their own
  family, not triangle/star (owner: 130-150 deg triples are stars).
- Curvy stream: a smooth-curve fit with a wobble residual instead of exact arcs.
- Each needs a generator block with ground truth in `make_pattern_fixtures.py` first, then the detector,
  then the owner's eye on real maps.

## Phase E. Replay side and intervals
Status: done (branch `ranelb/pattern-phase-e-classification`): objects.json schema v3, `class_miss`
block, recommender map side on rosu-pp + classes at `FEATURE_VERSION` 3, improver gap cut-off and
maintain bucket removed after held-out validation (`scripts/validate_recommend.py`, `docs/recommend.md`).
- `report.analyze` calls `label_objects` + the descriptors; `out/<tag>_objects.json` stores them.
- Per-class miss-rate block under the population gate (`min(20, max(8, 3 % of objects))`, n always quoted).
- Intervals: Wilson per class; bootstrap clustered by map; contrast against the overall rate.
- rosu-pp strains (aim/speed per 400 ms) as difficulty controls (`pip install -e ".[stars]"`).
- Bump `FEATURE_VERSION`; re-baseline the `recommend --json` byte-equality tests.

## Needed from the owner
1. Labels (phase A tool).
2. Vocabulary: are wide-jump walks their own family; a triangle/star angle cut-off; is an 8-object 45 deg ring a
   circle, a hexagon or both.
3. Descriptor cut-points for phase B (starting point above).
4. Where the real replays live (this worktree has no `replays/` or `out/`); needed for phase E and `judge_drift.py`.
5. OK to `pip install -e ".[stars]"` (network).
6. Scope: map-side + replay report only, or also the recommender's map side (`docs/NEXT.md` step 2).
