# Dashboard, skill profile and map recommendations

Goal: the web frontend stops being a viewer and starts teaching. A configurable
home dashboard says what you are weak at, and recommends specific maps — from
the maps you already own — that train exactly that weakness.

Status: design settled (see "Decisions"). Nothing implemented yet.

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
at `serve` boot (same rule as the index). `--status` optionally enriches rank
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

## Open questions

None blocking. Two known edges, accepted: orphaned `.osu` blobs count as
installed (blacklist covers it), and `scripts/mobile_audit.mjs` needs Playwright
installed locally to run.
