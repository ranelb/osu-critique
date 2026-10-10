# Beatmap rank status (`osu-critique status`)

A play on a **ranked/approved** map is pp-eligible; **qualified/loved** maps
have a leaderboard but award no pp; **pending/wip/graveyard** award nothing. The
split answers "how much of my practice is on pp-eligible maps", and it cannot be
read from the replay or the `.osu` alone.

```sh
osu-critique status out/ [--player NAME]
```

The map's online `BeatmapID` is parsed from the `.osu` `[Metadata]` (most played
maps carry one), then the IDs are batch-queried with osu! API v2
client-credentials — the same pair as `profile` (`osu_client_id` /
`osu_client_secret`, or `OSU_CLIENT_ID` / `OSU_CLIENT_SECRET`). No network is
touched without credentials; the command says so and exits instead of skipping.

Results cache to `out/beatmap_status.json` (`{beatmap_id: {status, stars,
set_id, ranked}}`), so later runs are offline.

## Two things the first parser got wrong

- the batch endpoint is
  `GET /api/v2/beatmaps?ids[]=...&ids[]=...` (at most **50 ids** per request) and
  it returns **`{"beatmaps": [...]}`**, not a bare list;
- `pending` is **unranked**, not pp-eligible, however "in progress" it sounds.

## Buckets

| bucket | statuses |
|---|---|
| pp-eligible | `ranked`, `approved` |
| leaderboard-only | `qualified`, `loved` |
| unranked | `pending`, `wip`, `graveyard` |

The report prints plays, share, in-game hours and hour-share per status, plus
the pp-eligible total.
