# The index

`osu-critique index` builds `out/index.sqlite`: a **projection** of the
`out/*_metrics.json` artifacts, not a second source of truth. Delete it and
rebuild — nothing is lost.

```sh
osu-critique index            # incremental: only changed artifacts
osu-critique index --rebuild  # drop every row and re-read out/
osu-critique index --check    # drift report; writes nothing, exits 1 on drift
```

`analyze` and `batch` upsert their run as they write the JSON, so the index is
never behind a run the CLI just produced. Set `OSU_NO_INDEX=1` to keep analysis
from touching the database at all (a locked or read-only index is already
non-fatal: the analysis prints one warning and continues).

## Why it exists

A listing page must not parse 3 000 JSON files, and a map page needs "every
attempt of this map" without a directory scan. The index holds **only the
scalars a list or map page filters, sorts and charts on**. The heavy blocks —
`autopsy`, `aim_mode`, `breakdown`, `profile`, `regions`, `quarters`,
`patterns`, `streams`, `sliders` — and the per-object records stay in the JSON
artifact and are read on demand for exactly one run.

Measured on the author's corpus (3 171 runs over 792 beatmaps): cold rebuild
4 s, no-op incremental sweep 0.1 s, 3.7 MB on disk. The first build walks the
lazer content store once (~9 GB, reads 32 bytes per file) to resolve each
beatmap md5 to its `.osu`; the resolved path is cached in `beatmaps.map_path`,
so later sweeps never pay it.

## Tables

| table | key | what |
|---|---|---|
| `runs` | `json_path` | one row per **artifact**. `run_id` is the replay md5 (or `tag:<tag>` for pre-schema files) and is **not** unique: 36 artifacts in the author's corpus are re-exports of 32 plays. |
| `beatmaps` | `beatmap_md5` | `[Metadata]` + `[Events]` parsed from the `.osu` (title, artist, creator, version, ids, background, audio, mode) and the cover cache path. |
| `annotations` | `id` | mirror of `out/annotations/<beatmap_md5>.json` (authored, canonical there). |
| `critiques` | `replay_md5` | mirror of `out/critiques/<replay_md5>.json` (authored, canonical there). |

Authored data is the one thing that is not derived. Deleting the database does
not delete an annotation or a stored critique; they are re-read from their
sidecar files.

## Rules the code enforces

- **A re-export is not a second play.** `index.runs_for_map()` keeps the newest
  artifact per `run_id`; `dedupe=False` shows both for diagnostics.
- **Missing pieces are flagged, not fatal.** A run analysed with
  `--no-objects` gets `objects_missing = 1`; a beatmap whose `.osu` is gone
  gets `metadata_missing = 1` (and the UI falls back to the metrics' `map`
  string). The four pre-schema artifacts have `schema_version = NULL`,
  `beatmap_md5 = ''` and no beatmap row.
- **`is_relax` is not `mods.RX`.** Autoplay (`AP`) runs are relax-like without
  the flag; the column is `mods.RX or mods.AP or aim_mode.is_relax`.
- **Watch joins move without the artifact.** `stars_by_md5.json`,
  `pp_by_replay.json` and `beatmap_status.json` are re-joined on every sweep,
  including for unchanged files, so running `stars` later fills `sr` on rows
  that were already indexed.
- **Schema drift is refused, not migrated.** `meta.schema_version` mismatch
  makes `connect()` raise with "run `osu-critique index --rebuild`".

## What is not here yet

- **Per-object rows.** Deliberate: every planned page is per-map or per-run,
  and one run's `_objects.json` is 154 KB — small enough to load whole. The
  table is additive when a question needs cross-map object queries.
- **Historical `replay_path`.** `analyze` records the `.osr` it read, but a
  sweep cannot: `replay_md5` is the replay's internal hash, not the file's md5
  (verified: 0 of 383 matched the file bytes), so resolving old rows means
  parsing every `.osr`. Do it as an explicit pass the day the renderer lands.
  The map file is already resolvable per beatmap via `beatmaps.map_path`.
