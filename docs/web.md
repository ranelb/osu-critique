# The web frontend

A local, read-only view over the analysed corpus: a beatmap-listing page, a page
per map, and a page per run. It is a **second frontend**, not a second
implementation — every number is read from the index (a projection of
`out/*_metrics.json`) or rendered by the analysis library itself.

```sh
pip install -e ".[web]"
osu-critique serve            # http://localhost:8765
```

`serve` sweeps the index on boot when it is missing or stale (`--no-index` to
skip), then serves until interrupted.

## What the pages show

| route | content |
|---|---|
| `/` | one card per beatmap: cover, difficulty, star pill, ranked status, attempts, best accuracy, last played. Search by artist/title/difficulty; sort by recency, accuracy, SR, attempts or pp; filter by status or "trustworthy only". |
| `/map/<beatmap_md5>` | hero cover + `[Metadata]` from the `.osu`, star/status pills, attempt table (sortable via htmx, no page reload), the cross-attempt block (first → latest per family/shape, with the `attempts` gate and verdict). |
| `/run/<run_id>` | the trust banner **first**, then accuracy/UR/counts/combo/hit-error/aim cards, a hit-error-over-time chart, a **collapsed** "where it went wrong" board set (see below), the objects worth looking at, the full object table on demand, and the deterministic report as **cards with tables** (see below). |
| `/api/objects/<run_id>` | the per-object JSON, verbatim as `analyze` wrote it. |
| `/api/map/<md5>`, `/api/runs` | the same data the pages render, for anything that wants JSON. |
| `/api/cover/<md5>?size=card\|hero` | the cached cover, fetched once from `assets.ppy.sh`. |
| `/feed` | the written digests as pages — stat cards, linked plays, map cards with art, and a **digest now** button (see [export.md](export.md)). |
| `/run/<id>/frames` | **501** — reserved for replay playback, deliberately unimplemented. |

`run_id` is the replay's md5, or `tag:<tag>` for the four pre-schema artifacts
that carry no md5. Re-exports of one play share an id; the newest artifact wins.

## Design rules

- **Server-rendered.** Jinja templates and one `app.js` (a few canvases and a
  lazy table). htmx handles the one partial (attempt sorting). No npm, no
  bundler, no serialising the corpus into the client.
- **One report, two renderers.** `report_sections.py` builds the deterministic
  critique as data — `kv` rows, notes with a tone (trust, time base, primary
  target), and tables — and `render_report()` is its terminal rendering, so the
  CLI text and the run page cannot drift. Sections with more than five table
  columns take the full grid width instead of being squeezed into a card.
- **Boards are computed server-side, drawn client-side.** `web/boards.py` turns
  `autopsy.misses.rows` + the object positions into zoomed five-note windows
  ranked by closest approach, the same misses as one playfield overview, and the
  cleanest stretch (a stream segment, or a quarter on a map with no long
  streams). The browser only draws circles and lines: no matplotlib, no frames,
  no extra request. The whole panel is a collapsed `<details>` — it costs one
  JSON blob in the page and nothing until you open it.
- **Critiques are stored, not recomputed.** The run page streams one LLM call
  and keeps the answer in `out/critiques/` with the hashes that say what it was
  made from; see [critiques.md](critiques.md).
- **Annotations are written here, in map time.** The run page's playhead stamps
  `t_map` (seconds on the `.osu` clock) so a note lands on the same objects on
  every attempt, even when the run's own rows are in another clock. See
  [annotations.md](annotations.md).
- **The trust banner comes first and is not a footnote.** A run whose judgement
  disagrees with the game's own counts gets a red banner and a different
  sentence, not just a different colour: `tests/test_web.py` asserts both.
- **The index is a projection.** Pages never treat a row as truth when the
  artifact is available: the run page renders from the metrics JSON, and the
  object table from `_objects.json`. The list page is the one place that trusts
  the index, because that is what it exists for.
- **Covers are lazy and optional.** `<img>` per visible card hits
  `/api/cover/...`, which caches to `out/covers/<set>-<size>.jpg`; a CDN 404
  leaves a `.missing` marker so a dead set is not re-fetched forever, and the
  page degrades to its gradient placeholder with no network at all.
- **Fonts and icons are shippable.** Torus is licensed for osu! only
  (`osu-resources/.../Fonts/Torus/LICENCE`), so the look uses Poppins (OFL,
  self-hosted woff2) and text mod pills. No osu! logo; the footer says who this
  is not affiliated with.

## Binding and auth

The default bind is `0.0.0.0:8765` with **no authentication** — the owner's
explicit choice, so the phone on the same network can open it. The consequence
is the whole history is readable by anything on that network. Set
`web.host` (or `--host`) to `127.0.0.1` to keep it local:

```json
{ "web": { "host": "0.0.0.0", "port": 8765, "index_on_boot": true,
           "cover_cache": true } }
```

Env overrides: `OSU_WEB_HOST`, `OSU_WEB_PORT`, `OSU_COVER_CACHE`.

## Testing

- `tests/test_web.py` drives every route through FastAPI's `TestClient` against
  a fixture corpus: list/search/sort/status filters, the map page's attempt
  order and cross-attempt block, the trust banner's two renderings, the objects
  API, 404s, the reserved frames route, cover cache hits, offline covers, and
  boot-indexing.
- The map page has a **golden structure test** — headings, attempt order and
  exact numbers — rather than a byte-for-byte HTML snapshot. Markup churn is
  allowed; silently changing what the page says is not.
- The core suite runs **without** the `[web]` extra (the module skips itself);
  CI installs the extra on one interpreter only.
- Visual checks are human-in-the-loop: run `serve`, open the pages, look.
  `docs/screenshots/` is where Playwright drops them — **gitignored**, because
  a screenshot of this corpus carries the player's real numbers. A commit-able
  set has to be rendered from the synthetic fixture corpus (0.20.0 polish).

## Not here yet

Replay playback (fenced for now — the route and the data columns exist so it
will not need a schema change).
