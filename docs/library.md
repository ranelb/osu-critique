# The library

`osu-critique library scan` fills `library_beatmaps` in `out/index.sqlite`: one
row of **map-side features for every `.osu` on disk**, played or not.

```sh
osu-critique library scan              # incremental: only new/changed maps
osu-critique library scan --rebuild    # drop every row and re-parse
osu-critique library scan --status     # also fetch online rank status (API v2)
osu-critique library scan --source DIR # scan only DIR (.osu/.osz); repeatable
```

This is the other half of the analysis. The `out/*_metrics.json` artifacts say
what happened in a play; `library_beatmaps` says what a map *is*, so a
recommendation can score a map no replay ever touched. Nothing here needs a
replay, a key or a network.

## Why it exists

`runs` covers the ~800 maps you have played. The lazer content store, `maps/`
and `stable`'s `Songs` hold several thousand more, and a recommendation that can
only suggest maps out of your own history is a shuffle button, not a coach.
The scan is also where the map's *material* gets measured — spacing buckets,
sustained runs, how much of the map turns back on itself — which no replay file
contains.

Measured on the owner's machine (5 672 `.osu` blobs, 5 589 of them parsable):
**150 s cold, 0.6 s no-op incremental**, ~150 rows/s. The 77 unparsable blobs
are misaligned hit-object lines and degenerate slider curves that the pinned
`slider==0.8.4` rejects; they are counted and skipped, never guessed at.

## What a row holds

First-class columns (what the gate and a card need):

| column | meaning |
|---|---|
| `sr` | NM star rating from rosu-pp. **NULL** without the `[stars]` extra |
| `bpm`, `length_ms`, `ar`, `od`, `cs`, `hp` | the map as written (no mods) |
| `n_objects`, `n_circles`, `n_sliders`, `n_spinners`, `slider_ratio` | shape |
| `dense_share`, `stream_share`, `jump_share`, `bigjump_share` | spacing buckets: ≤2 r, 2–4 r, 4–7 r, >7 r |
| `anti_flow_share`, `flow_share` | turn ≥135° / ≤45° |
| `sustained_share`, `sustained_max`, `sustained_nps` | objects inside a detected sustained run, the longest run, and its median notes/s |
| `kiai_share`, `density`, `strain_aim_max`, `strain_speed_max` | context |
| `mode`, `set_id`, `beatmap_id`, `rank_status` | identity and eligibility |

Everything else rides in `features_json` (angle counts, strain percentiles, SV
and BPM ranges, per-bucket counts) so a new feature does not need a migration.
`FEATURE_VERSION` 3 adds `features_json["rosu"]` (stars, aim, speed, slider_factor,
speed_note_count, aim/speed difficult strain counts, from rosu-pp) and
`features_json["classes"]` (`any_shape`, `any_walk`, `any_curve` and `keys`: the share of
objects per `class_keys` name, from `metrics/classes.py`). The recommender reads these; the
spacing columns above are kept as context and are no longer scored.
The spacing buckets and sustained runs come from the analysis library itself —
`metrics.patterns`, `metrics.structure.annotate`, `metrics.streams.find_runs` —
so a map is described by the same definitions a play is judged with. There is
no second pattern detector to drift.

## Rules

- **Derived, disposable.** Like every other table, deleting `out/index.sqlite`
  loses nothing; `library scan` rebuilds it. Note `index --rebuild` deletes the
  database *file* (an older schema cannot be opened to drop tables), so the
  library goes with it — rescan, and `recommend` will say so until you do. A row whose file disappeared is
  deleted — a map you removed cannot be recommended.
- **Incremental by `(path, mtime, size, FEATURE_VERSION)`.** Bumping
  `library.FEATURE_VERSION` re-extracts every row on the next scan; that is the
  migration mechanism, not a schema change.
- **No boot sweep.** `serve` does *not* rescan the library on start: the walk
  plus parse is ~150 s cold and a boot stall on a tool read from a phone is
  worse than a stale candidate list. Re-run `library scan` after an import; the
  dashboard reports the scan age instead of pretending it is fresh.
- **SR is optional, absence is honest.** Without `rosu-pp` the scan still runs
  and writes `sr = NULL`; the recommendation gate treats NULL as "cannot rank
  this map", never as zero stars. `pip install 'osu-critique[stars]'`.
- **`--status` is the only network path** (osu! API v2, the same
  client-credentials pair as `profile`/`status`). It writes the shared
  `out/beatmap_status.json`, so a play and a candidate never disagree about
  whether a map is ranked.

- **Skipped is not failed.** A mania map with hold notes (`x,y,t,128,hs,endTime:hitSample`)
  is read by `slider` as a spinner and raises "end_time should be an int". The
  scan counts it under `skipped` / `skipped_reasons` (`mania hold notes`) and the
  exit code stays 0. Catmull sliders (`C|…`) used to fail with a `TypeError` on
  NumPy >= 2.5 (slider 0.8.4 calls `float()` on a 1x1 array); `io/beatmap.py`
  swaps in an equivalent `Catmull.__call__` when the library's own breaks.
  `tests/fixtures/parse/` holds one map for each.

## Why not read lazer's Realm database

`client.realm` would save the file walk and carry a cached star rating, but:

- no Python reader exists — the maintained one is Rust (`osu-realm-util`),
  version-bound to a Realm format, covers 15/23 `Beatmap` columns and does no
  difficulty calculation; the TypeScript one died in 2022;
- Realm never carries the spacing/flow/sustained features the scorer needs, so
  the `.osu` parse survives the "overhaul" anyway;
- it is lazer-only, while `stable`, `.osz` archives and a plain folder are all
  supported sources.

One accepted cost: an orphaned blob from a deleted beatmapset still looks
installed. The blacklist is the escape hatch.

## Fixtures

`tests/fixtures/library/` holds six maps whose features are known by
construction (jumps, stream, anti-flow, slider-heavy, mania, too short) and
contains no replays, so nothing needs anonymising. Regenerate with:

```sh
python scripts/make_synthetic_fixtures.py --library
```

## Geometry block (FEATURE_VERSION 2)

`features_json["geometry"]` = `{coverage, shapes, labels}` from `metrics/geometry.py` +
`metrics/rhythm.py`: share of notes explained by a shape, per-shape segment/note counts, and
per-label ("spaced circle stream", "triangle jumps") segment/note counts. Not a column: it is
a long-tail feature, read from the JSON. `patterns.bucket` features are unchanged and still
what `recommend.py` used to read; since `FEATURE_VERSION` 3 it reads `rosu` and `classes`
instead (`docs/recommend.md`).
