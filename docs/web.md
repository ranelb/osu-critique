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
| `/run/<run_id>` | the trust banner **first**, then accuracy/UR/counts/combo/hit-error/aim cards, a hit-error-over-time chart, and then five folds: "where it went wrong", the objects worth looking at, the deterministic report as **cards with tables** (see below), the stored LLM critique (read-only, with a link into the tab), and the notes. A left rail jumps between them. |
| `/api/objects/<run_id>` | the per-object JSON, verbatim as `analyze` wrote it. |
| `/api/map/<md5>`, `/api/runs` | the same data the pages render, for anything that wants JSON. |
| `/api/cover/<md5>?size=card\|hero` | the cached cover, fetched once from `assets.ppy.sh`. |
| `/ask` | the selection picker (replays, whole maps, time ranges, a mod filter), an optional question, the generate button, the summary as text, and the stored answers — the answer first, the input it read underneath. Old `/critique` links 301 here. See `docs/ask.md`. |
| `/ask/<hash>` | one stored answer: the question, the answer, the exact summary it read, and the selection. |
| `/feed` | the written digests as pages — stat cards, linked plays, map cards with art, and a **digest now** button (see [export.md](export.md)). |
| `/run/<id>/frames` | **501** — reserved for replay playback, deliberately unimplemented. |

`run_id` is the replay's md5, or `tag:<tag>` for the four pre-schema artifacts
that carry no md5. Re-exports of one play share an id; the newest artifact wins.

## The rail

Every page except the maps grid carries a left rail (`partials/rail.html`): one
anchor per block, built from a `toc` list the route puts in the context, so it
cannot drift from the markup. Entries carry a count when the block holds a
countable thing — objects, sections, notes, attempts — and no count when a count
would only restate the cards at the top.

Sticky above 880 px — 172 px wide, narrowing to 142 px under 1160 px — and a
horizontal chip strip only below that. A column beside the title beats a chip
bar pinned above it, which was the first version and read as clutter. The active entry is the
last block whose top crossed 28 % of the viewport, recomputed on scroll, resize
and `toggle`: **not** an IntersectionObserver, because opening a fold moves every
block below it without a scroll event, and reconstructing "what is on screen"
from enter/leave events gets subtle. On a page too short to scroll, the last
entry wins.

## Folds

Heavy blocks are `<details class="fold">`, closed by default, with a **peek** line
under the title. A peek states what is inside (the rule, the count, the model and
when) and never a value that the cards already show — "37 of 153 objects: every
miss and every non-300, in map order", not "37 objects, worst first".

The deterministic report's fold carries **copy** and **text**. The text is
inlined in the page as `<script type="application/json" id="report-text">` — the
same `report_sections.to_text` the CLI prints — so copying needs no fetch and
happens inside the click gesture. That matters: `execCommand("copy")` after an
`await fetch(...)` has lost the user activation and silently fails, which is
exactly how the first version broke on the LAN address. `navigator.clipboard`
also needs a secure context, so plain http falls back to a hidden textarea and
`execCommand`; if even that fails, the text is dropped into the fold and opened.

`text` is a plain link to `/run/<id>/report.txt`: no JavaScript, no clipboard,
always works. Copy is the convenience, not the only access.

## Design rules

- **Server-rendered.** Jinja templates and one `app.js` (a few canvases and a
  lazy table). htmx handles the one partial (attempt sorting). No npm, no
  bundler, no serialising the corpus into the client.
- **The ask page is the only place an answer is generated.** The run page shows
  what is stored for that run — an answer when one exists, an older per-run
  critique read-only otherwise — and links to `/ask` with the run pre-selected.
  Two generation paths meant two prompts for the same replay.
- **A question is part of the input, not a UI overlay.** `?q=` is written into the
  text as `## The question` before the header, and therefore into the hash; the
  same selection with a different question is a different artifact. The page
  keeps the summarise-then-ask order: set the question, read the exact text that
  will be sent, then generate.
- **The answer sits above the numbers.** On the run page and on the tab, the LLM
  critique comes before the deterministic report: the answer is what you read
  first, the tables are what you check it against. The rail follows the same
  order.
- **Replay rows carry a dimmed cover.** `/api/cover/<md5>?size=card` as a CSS
  background plus a gradient, so a row is recognisable at a glance without
  changing its height; `loading` is irrelevant for a background, and the images
  are cached after the first look.
- **The pickers page on scroll.** Each list starts with 40 rows and ends with a
  sentinel `<li data-more>`; `app.js` watches it with an `IntersectionObserver`
  rooted at the list and fetches `/critique/rows?kind=…&offset=…`, which returns
  the next rows plus a fresh sentinel. Hand-rolled on purpose: htmx's `revealed`
  watches document scroll, and scrolling an inner panel fires no such event. The
  offsets skip the ids already excluded *in SQL*, so a page boundary cannot
  repeat or drop a row.
- **Static assets are busted by a content fingerprint**, not the release number:
  editing `style.css` and reloading used to serve the old file, which reads
  exactly like a CSS bug. `?v=` changes when the files change.
- **Selection state is the URL.** `/critique?runs=…&maps=…&since=…`: every "add"
  and "remove" is a link, the page is server-rendered on each change, and a
  selection can be bookmarked or pasted into a chat. Nothing is remembered
  between requests, so nothing can desync.
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
- **Critiques are stored, not recomputed.** The tab streams one LLM call per
  selection and keeps the answer *and the summary it read* in
  `out/answers/`, keyed by a hash over both; the same selection opens the
  stored one instead of paying twice. See [ask.md](ask.md).
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
