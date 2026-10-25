# Export and the digest

Two halves of the same loop:

- **export** pulls every local score's replay out of osu!lazer's database;
- **digest** analyses the ones that are new, summarises what changed, and says
  which maps deserve another attempt — deterministically, without a model.

Both are **opt-in**. Nothing here schedules itself, and export does nothing at
all until you turn it on.

## Export

```sh
osu-critique export                 # status: enabled? binary? how many .osr?
osu-critique export --install       # fetch the pinned BeatmapExporter (sha256)
osu-critique export --run           # actually export (needs export.enabled)
osu-critique export --run --status ranked,loved
osu-critique export --run --prune-player ran27
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
config silently hides loved/graveyard plays (it hid 171 of the author's plays
from this corpus). With no statuses configured the command sends `reset` first,
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
osu-critique digest                  # ingest new replays + write today's digest
osu-critique digest --no-ingest      # summarise only
osu-critique digest --stdout         # print, write nothing, move no marker
osu-critique digest --since 2026-10-01T00:00:00
```

The window is `out/digests/.last` (an ISO timestamp, plus the file's mtime for
the ingest side). With no marker the first digest looks back 24 hours.

**Ingest** is the only expensive part: it lists exported `.osr` files newer than
the marker, pairs them, analyses them and indexes them. A replay is skipped when
its md5 is already in the index, so a second run is a no-op — that is what makes
it safe on a timer. First-time backfill can be hundreds of replays (the author's
was 171 replays / 156 s after the status filter was fixed).

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

```
GET /feed     # the page
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
