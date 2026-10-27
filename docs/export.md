# Export and the digest

Two halves of the same loop:

- **export** pulls every local score's replay out of osu!lazer's database;
- **digest** analyses the ones that are new, summarises what changed, and says
  which maps deserve another attempt — deterministically, without a model.

Both are **opt-in**. Nothing here schedules itself, and export does nothing at
all until you turn it on.

Once it is on, a **digest exports first**: `digest` runs the exporter, then
ingests what came back, then summarises. So "digest now" means "get my latest
plays and tell me about them", not "read whatever something else exported". The
feed page states which of the two it is at the top, and says so loudly when the
exporter is enabled but missing.

`osu-critique setup` writes the flag (it merges into your config, it does not
replace it — that is how this setting once vanished for an evening).

## Export

```sh
osu-critique export                 # status: enabled? binary? how many .osr?
osu-critique export --install       # fetch the pinned BeatmapExporter (sha256)
osu-critique export --run           # actually export (needs export.enabled)
osu-critique export --run --status ranked,loved
osu-critique export --run --prune-player TestPlayer
```

Why this exists: osu!lazer exposes no export interface — no CLI, no IPC — and
its Realm database needs the .NET SDK. Reading it from Python was investigated
and rejected (`docs/ROADMAP.md`, item 7a). BeatmapExporter (MIT, pinned
`v2.8.0`) is the reader; this module drives its menu, which is text-driven
(`status …` / `reset`), so it is a documented interface rather than screen
scraping.

**It is disabled by default** because it reads your game database and can move
thousands of files:

```json
{ "export": { "enabled": true, "statuses": [], "binary": null } }
```

`export.statuses` empty means **no filter — export everything**. That matters:
BeatmapExporter remembers its last filter, and a `status=ranked` left in its
config silently hides loved/graveyard plays (it silently hid 171 plays from the
reference corpus). With no statuses configured the command sends `reset` first,
so the filter cannot linger.

`--prune-player NAME` deletes exported replays whose filename does not start
with `NAME` — the Realm also holds other players' downloaded replays. It is off
by default: deleting files should be something you asked for.

One run moves the delta and takes about a second for ~3 400 scores. To schedule
it, use your own timer (the tool will not add one):

```ini
# ~/.config/systemd/user/osu-critique-export.service
[Service]
Type=oneshot
ExecStart=%h/.local/bin/osu-critique export --run
Environment=OSU_EXPORT_ENABLED=1
```

## Digest

```sh
osu-critique digest                  # export (if enabled) + ingest + write
osu-critique digest --no-ingest      # summarise only
osu-critique digest --no-export      # do not touch the osu! database
osu-critique digest --stdout         # print, write nothing, move no marker
osu-critique digest --since 2026-10-01T00:00:00
```

**A digest pulls its own replays.** When `export.enabled` is true, `digest` runs
the exporter first, so "digest now" on the feed really means "fetch my latest
plays and summarise them" rather than "read whatever some other tool exported".
With export off it only reads the exports folder and says so when that is empty.

Three markers, because "new" has three meanings and conflating them loses plays:

| marker | meaning |
|---|---|
| `out/digests/.ingest` | the newest **exported-file mtime** an ingest pass has already seen. Advanced only by an ingest, and only to the newest file that exists — never to "now". |
| `out/digests/.window` | the newest **play** the last digest actually reported. A digest that shows nothing leaves it alone, so an unreported play stays in the next window instead of vanishing. |
| `out/digests/.last` | when the last digest ran (fallback for folders written before the other two). |

A play also counts as new when **this run just ingested it**, whatever its
timestamp — the late-export case (played last night, exported tonight).

**Ingest** is the only expensive part: it lists exported `.osr` files newer than
the marker, pairs them, analyses them and indexes them. A replay is skipped when
its md5 is already in the index, so a second run is a no-op — that is what makes
it safe on a timer. First-time backfill can be hundreds of replays (171 replays
took 156 s once the status filter was fixed).

The digest itself names the plays, compares a typical one against your history
(timing spread as a share of the 300-window, and miss rate per 100 objects —
both difficulty-normalised), and for maps with more than one attempt names the
**consistent weaknesses** and the **swings**. With one attempt it says there is
nothing structural to compare, instead of inventing a pattern. Aim-at-demand is
deliberately absent: it needs the banded per-object data, which `report
--history <metrics>` computes for one run at a time.

Nothing in this path calls a model. The footer of every digest says so.

## The feed

`/feed` in the web frontend lists the digests, newest first. It is a **page**,
not a text dump: each digest renders as

- a header (date, "199 plays over 100 maps", the window, what ingest did);
- stat cards for **timing spread** and **miss rate** as percentiles against
  earlier runs, each with a bar, plus **best** and **worst** play (linked to
  their map);
- the plays table — every row's map links to `/map/<md5>`, every row has
  `open →` to the run;
- **maps worth another look**: cover cards (art from the same lazy CDN cache),
  star pill, `+N` for this window, mapper, attempt count, and the named
  consistent weaknesses / swings as pills — each card links to its map page.

Each digest is written twice: `…md` (canonical text, for the CLI and for
pasting into anything) and `…json` (the same data structured, which the feed
renders). A digest without the JSON sidecar — anything written before 0.20 —
still appears, collapsed, as its text under "read the text".

**digest now** on that page runs the same thing the CLI does (`POST
/feed/digest`): ingest, analyse, write, redirect back. It can take a minute when
there are new replays, so the button disables itself and says so; a second click
while one is running gets a 409 rather than two concurrent digests.

```
GET  /feed          # the page
POST /feed/digest   # ingest + write one now (optional form field: since)
```

## Files

| path | meaning |
|---|---|
| `out/digests/YYYY-MM-DD_HHMM.md` | one digest per run, canonical text |
| `out/digests/YYYY-MM-DD_HHMM.json` | the same digest structured, read by `/feed` |
| `out/digests/.last` | the window marker (ISO timestamp) |
| `~/.local/share/osu-critique/bin/` | the installed BeatmapExporter |
| `~/.config/osu-critique/config.json` | `export.enabled`, `export.statuses`, `export.binary` |

Environment overrides: `OSU_EXPORT_ENABLED`, `OSU_EXPORT_STATUSES`,
`OSU_EXPORT_BINARY`, `OSU_EXPORT_BIN_DIR`, `OSU_EXPORT_TIMEOUT`.
