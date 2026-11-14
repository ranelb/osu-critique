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
| `/` | the **dashboard**: configurable widgets — form (30/90 d), recommendations, skill profile, weak spots, accuracy+UR trend, activity calendar, recently played, what's new. See [The dashboard](#the-dashboard). |
| `/maps` | one card per beatmap: cover, difficulty, star pill, ranked status, attempts, best accuracy, last played. Search by artist/title/difficulty; sort by recency, accuracy, SR, attempts or pp; filter by status or "trustworthy only". |
| `/learn` | the glossary: every term the dashboard prints, defined once with an anchor, a one-liner and how it is computed. Linked from every card label (native `title` tooltip) and from the widget headers. See [Teaching](#teaching). |
| `/settings` | dashboard layout (player, stretch, card count, buckets, widget order/windows), the blacklist manager, and read-only resolved paths. See [Settings](#settings). |
| `POST /blacklist`, `POST /blacklist/remove` | the × on a card and the manager: add/remove a difficulty or a whole beatmapset. Canonical in `out/blacklist.json` (see [recommend.md](recommend.md)). |
| `/map/<beatmap_md5>` | hero cover + `[Metadata]` from the `.osu`, star/status pills, attempt table (sortable via htmx, no page reload), the cross-attempt block (first → latest per family/shape, with the `attempts` gate and verdict). |
| `/run/<run_id>` | the trust banner **first**, then accuracy/UR/counts/combo/hit-error/aim cards, a hit-error-over-time chart, and then five folds: "where it went wrong", the objects worth looking at, the deterministic report as **cards with tables** (see below), the stored LLM critique (read-only, with a link into the tab), and the notes. A left rail jumps between them. |
| `/api/objects/<run_id>` | the per-object JSON, verbatim as `analyze` wrote it. |
| `/api/map/<md5>`, `/api/runs` | the same data the pages render, for anything that wants JSON. |
| `/api/cover/<md5>?size=card\|hero` | the cached cover, fetched once from `assets.ppy.sh`. |
| `/ask` | the selection picker (replays, whole maps, time ranges, a mod filter, an attempts-per-map filter), an optional question, the generate button, the summary as text, and the stored answers — the answer first, the input it read underneath. Old `/critique` links 301 here. See `docs/ask.md`. |
| `/ask/<hash>` | one stored answer: the question, the answer, the exact summary it read, and the selection. |
| `/feed` | the written digests as pages — stat cards, linked plays, map cards with art, and a **digest now** button (see [export.md](export.md)). |
| `/run/<id>/frames` | **501** — reserved for replay playback, deliberately unimplemented. |

`run_id` is the replay's md5, or `tag:<tag>` for the four pre-schema artifacts
that carry no md5. Re-exports of one play share an id; the newest artifact wins.

## The dashboard

## Visual design

The pages are built out of two things the game already owns: **the cover art of
the maps** and **the four judgement colours**. Colour is semantic, not
decoration, and that is the whole system:

| token | value | role |
|---|---|---|
| `--bg` / `--panel` | `#08070d` / `#171223` | violet-black ink and surface — a neutral grey makes every cover look pasted on |
| `--pink` | `#ff66aa` | osu!'s brand: interaction, the primary action, the current nav item. Nothing else. |
| `--cyan` | `#66ccff` | a 300, and any figure at or above your own median |
| `--green` / `--c100` | `#9acd32` / `#88b300` | a 100: the easier half of a split, ranked status |
| `--gold` | `#ffcc22` | a 50: below your median, the improver bucket, a warning |
| `--red` / `--miss` | `#ff5f6d` / `#ed2d3f` | a miss, the gap you are being shown |

Two faces, each with a job: **Poppins** (the shippable stand-in for osu!'s Torus,
see `static/VENDOR.md`) carries prose and display; **JetBrains Mono** carries
every number, table head and bar key, because columns have to line up. The type
scale is six named steps (`--t-label` … `--t-h1`); a new block picks one instead
of inventing another `0.84rem`.

Structural rules, all of which the dashboard follows:

- **A section is a rule and air.** `.panel` has no background, no radius and no
  border except a 1px top rule. Cards are reserved for things you can pick — a
  map, a recommendation.
- **An image earns its place.** The dashboard opens on the cover of the map you
  played last (`dashboard.hero()`, `/api/cover/<md5>?size=hero`), sharp on the
  right, with the 30-day figures on ink on the left. Recommendation cards carry
  their map's cover; recent plays carry a 44px thumb. The covers saturate and
  scale 5 % on hover, which is the only hover transition in the app.
- **One motion.** The accuracy line draws itself once, `pathLength="100"` and a
  CSS `stroke-dashoffset` animation, no JavaScript. Everything else is static.
  `prefers-reduced-motion` removes it.
- **No ALL-CAPS chrome.** Section headings, rail titles, table heads and form
  labels are sentence case. `text-transform: uppercase` appears nowhere.
- **The chart colour is the verdict.** A week's dot is cyan at or above your own
  median and amber below it; the median is drawn as a dashed line. The legend
  states the rule rather than a gradient.

`/api/cover/<md5>` resolves through `library_beatmaps` when `beatmaps` has no
row: a recommendation is usually a map you have never played, and the played
maps table cannot answer for it.

### The widgets

`/` is a page of **widgets**, and the widget list *is* the settings: order,
on/off, and a window where a window means something. The catalogue lives in
`dashboard.WIDGETS` (id, label, allowed windows); a template cannot fall out of
sync with it because the page renders `partials/dash/<id>.html` per enabled
widget, in order.

- **The layout is a file**, `~/.config/osu-critique/dashboard.json` (0600, next
  to `config.json`), not a cookie: the phone on the LAN and the desktop see the
  same page. Unknown widget ids are dropped and missing ones defaulted, so an
  old or hand-edited file never blanks the dashboard. `?saved=1` is the only
  query parameter, and it only switches the word "saved." on.
- **The player is resolved, not assumed.** `dashboard.json`'s `player` is a
  pin; blank means "the most-run player in the corpus". A pinned name the
  corpus does not contain falls back to that, rather than showing an empty page.
  The resolved name is printed under the title so a wrong pin is obvious.
- **Recommendations and the skill profile are one call.** The recommender
  produces both halves in one pass (`recommend.build`), and the dashboard pays
  for it only when a widget shows either. Measured on the owner's corpus: ~0.4 s
  cold, ~0.15 s warm — a page a phone can wait for.
- **No library scan on boot.** The dashboard reports the scan's age instead
  ("library: 5589 maps, scanned 2.3d ago" or "not scanned" with the command). A
  cold scan is ~150 s and a boot stall on a phone-first tool is worse than a
  stale candidate list.
- **Charts are precomputed geometry.** The trend widget's points are turned
  into an SVG polyline in Python, the calendar into a level 0–4 per day; the
  template does no arithmetic. That is also why the dashboard needs no
  JavaScript: no canvas, no client-side data.

## Settings

One `<form>` posts the whole layout. Widgets are rows with a checkbox, a window
select and ↑/↓ buttons, so a toggle and a move made in the same click are
saved together — the buttons are `<button name="move:<id>" value="up">`, not a
second form. Saving writes the file and redirects (`302`), so the page works
with no JavaScript and a refresh cannot re-post.

Read-only on purpose: the resolved paths and the bind address. The server is
unauthenticated on the LAN, and a page that can write an API key is a page that
can leak one.

## Blacklist

The × on a recommendation card blocks a difficulty; the second button blocks
the whole beatmapset. Both post to `/blacklist`, which writes the sidecar and
mirrors it into the index. The manager in settings lists both scopes with an
unblock button, because a list you cannot undo is a trap.

The same × sits on every `/maps` card (a sibling of the card link — a form
inside an `<a>` is invalid markup, so the card is wrapped) and on the map page,
where "whole set" is offered too. A blocked map is dimmed with an unblock
button, so nothing becomes unreachable.

## "Open in osu!"

`/learn` is not the only way out of the page: a recommendation card and the map
page carry an **open in osu!** button. It posts the map's md5 to `/open`, and
the **server** launches the game:

1. the md5 is looked up in `library_beatmaps` (then `beatmaps`) — the client
   never supplies a URI, so the route cannot be turned into "open anything";
2. the id becomes `osu://b/<beatmap id>` (or `osu://s/<set id>` when only a set
   id exists) — lazer's `OpenBeatmap` / `OpenBeatmapSet` actions;
3. **the flatpak app id is launched directly** when the scheme's desktop entry
   starts one, then `gio open`, then `xdg-open`;
4. the launch is *checked* (see below), and the redirect says what happened
   (`?open=ok`, `open=error`, `open=no-id`).

### Why the launch path is not just `gio open`

Measured on osu!lazer 2026.1005 (flatpak), 2026-11-14, and the reason this
button appeared to do nothing while the page said "osu! was asked to open that
map":

- The flatpak's exported `sh.ppy.osu.desktop` runs
  `flatpak run … --file-forwarding sh.ppy.osu @@ %F @@`. `%F` is file
  forwarding: a **URI** is treated as a path, so `gio open osu://b/1876815`
  becomes `error: Failed to open ‘/tmp/osu:/b/1876815’` inside flatpak. The
  launcher is detached, so **`gio open` still exits 0** — a silent failure that
  reads as success.
- `flatpak run sh.ppy.osu osu://b/1876815` skips that rewrite and the running
  game receives the link (verified in its log: `BeatmapSetOverlay` focus at the
  moment of the POST).

So `_launch_candidates()` reads the `Exec=` line of whatever owns
`x-scheme-handler/osu`, extracts the flatpak app id, and prefers
`flatpak run <id> <uri>`; `gio open`/`xdg-open` remain for non-flatpak installs.
`_launch_uri()` waits up to 3 s for the launcher: a non-zero exit is a real
failure and its stderr goes to the server log, while a still-running child means
the game is starting and counts as launched.

An id that is not a real beatmap id is not an error: lazer ignores it silently,
so the page cannot promise more than "handed it over".

Doing it server-side is not a preference: a browser only launches an unknown
scheme if it delegates to the OS, which Firefox-based browsers do not do for
`osu` unless `network.protocol-handler.external.osu` is `true` — without it Zen
just opens a tab showing `osu://b/1234`. A phone has no handler at all. The
server round trip works from any browser, and from the phone.

The map page keeps the raw `osu://b/<id>` link next to it as a "direct link",
which is the right thing when the page is served from a different machine than
the one running the game. A map imported from a folder without online ids
degrades to a disabled "no online id" label, reason in the tooltip.

## Teaching

The dashboard's vocabulary — "band-corrected miss rate", "excess", "improver",
"comfort SR" — is defined **once**, in `web/glossary.py`, and everything else
points at it:

- `learn.html` renders the whole list at `/learn`, grouped into numbers /
  profile / recommendations, with stable anchors (`#improver`).
- `partials/gloss.html` has two macros: `gloss(id, label)` turns a label into a
  link whose `title` is the one-liner (hover on a desktop, long-press on a
  phone, no JavaScript), and `learn(id)` is the `?` in a widget header.
- `docs/` stays the authority for formulas; each entry links there instead of
  restating a derivation, so there is exactly one wording and exactly one
  formula source.

`tests/test_dashboard.py` asserts the mechanical half: every `href="/learn#…"`
on `/` resolves to an anchor that exists, so a rename cannot leave a dead
tooltip behind.

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

On a phone the strip sticks **below** the header, at `top: var(--topbar-h)`.
`initRail` measures the header and the strip into `--topbar-h` / `--rail-h` on
load and resize instead of hardcoding a padding that moves with the font — it
used to stick at `top: 0` with `z-index: 6` under a 61.5 px header with
`z-index: 10`, so the whole navigation was invisible exactly while scrolling.
`main [id]`'s `scroll-margin-top` is the same sum, or a chip jumps to a block
that is hidden behind both bars. The active chip is scrolled into view when the
section changes.

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

## Phones

The owner reads this on a phone over the LAN, so 320–430 px is a supported
width, not a degraded one. What that costs:

- **A table scrolls inside its panel.** Every `<table class="data">` sits in a
  `.tscroll` (or `.rscroll` for the report), which is `overflow-x: auto` with
  `min-width: max-content` on the table. Without that the page widens to the
  table and the header scrolls off the screen — measured at 507 px on a 390 px
  map page before this rule existed. Grids use `minmax(min(100%, Npx), 1fr)` for
  the same reason: a bare `minmax(430px, 1fr)` is a hard 430 px floor.
- **The listing becomes dense rows below 620 px.** A 3.2:1 cover per map is five
  screens for 24 maps, so the card reflows to a 64 px thumb plus three lines:
  title, difficulty and mapper, then attempts/best/last. The SR and status pills
  and the difficulty name are duplicated in the card body (`.row-badges`,
  `.row-version`, hidden above 620 px) because the cover is too small to carry
  them. Duplication is CSS-only; the desktop card is untouched.
- **Answers are rendered markdown.** `osu_critique/markdown.py` renders the
  subset a model actually writes (headings, paragraphs, lists, quotes, fences,
  tables, bold/italic/code/links) and escapes everything first — the body is
  untrusted text. Templates use `{{ body | md | safe }}`. The deterministic
  report is **not** markdown and keeps its cards and tables.
- **Controls and prose size up.** Text inputs take a 16 px floor on phones (iOS
  zooms on focus below that and never zooms back); `pre.report`/`pre.scope-text`
  go from 12 px to 14; `.rkv` stacks its label above its value instead of
  squeezing the value into a 175 px column. Chips and the picker's +/× get a
  40 px floor, and the miss boards go two-up (`150px` tiles) instead of one per
  row.
- **The ask page's action is always reachable.** Below 620 px a bar sticks to
  the bottom of the window with the selection count and the generate button. It
  is a `<button form="scope-form">`, not a second form: no duplicated hidden
  inputs, one submit handler, and it still submits without JavaScript. The bar
  is `display: none` above 620 px, where the panel is already in view.

The stat cards are one row (`grid-auto-flow: column`) only while there is a rail
beside them; below 880 px they flow as rows again. Column flow plus a template
of two columns is how six cards became six 60 px slivers.

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
- **Covers are lazy, sized and optional.** `<img>` per visible card hits
  `/api/cover/...`, which caches to `out/covers/<set>-<size>-v<N>.jpg`; a CDN 404
  leaves a `.missing` marker so a dead set is not re-fetched forever, and the
  page degrades to its gradient placeholder with no network at all. The sizes
  are `hero` (`cover@2x`, the map page), `card` (`card@2x`, a retina tile) and
  `thumb` (`card`, 13–34 KB, what a phone's 64px row and a dimmed picker
  background need); a listing tile is `src=thumb srcset="…card 2x"` so the
  browser picks by density. **`fetch` takes the size** — it used to ignore it and
  download `cover@2x` for every variant, so a "card" was 1800x500 and 24 tiles
  were 5 MB; `CACHE_VERSION` in `covers.py` re-fetches at the right variant once
  and deletes the stale file.
- **The home-screen icons are generated, not committed.** `web/icons.py` writes
  the 180/192/512 PNGs with `zlib` (a pink disc on the page background, inset to
  survive a maskable crop) and the route caches them for a week. `manifest.webmanifest`
  is `display: standalone` with `theme_color` in `base.html`, so "add to home
  screen" opens without browser chrome. No service worker: the data is a local
  server, and a cached shell would only lie about it.
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
- Layout has one automated guard: `scripts/mobile_audit.mjs` drives Chromium at
  320/360/390/430 px over `/`, a map, a run, `/feed`, `/ask` and a stored answer,
  and **fails on document-level horizontal scroll**. It also warns on touch
  targets under 32 px and text under 12 px. Needs Playwright (`npm i playwright`,
  or `PLAYWRIGHT_MODULE=` + `CHROMIUM_PATH=`); it is the only Node dependency in
  the repo and it never ships.

## Not here yet

Replay playback (fenced for now — the route and the data columns exist so it
will not need a schema change).
