# Annotations

The player's own notes — what you noticed, where, and why — written once and
read by every attempt at that map. The LLM critic gets them as its own prompt
block, so its critique can start from your hypothesis instead of guessing.

```sh
osu-critique annotate add --map <beatmap_md5> --t 2:14.312 --tag kiai \
    "the second kiai is where the rhythm breaks"
osu-critique annotate add --map <beatmap_md5> --run <replay_md5> \
    "felt sloppy, cold hands"
osu-critique annotate list [--map <md5>] [--run <md5>] [--json]
osu-critique annotate rm <note_id>
```

In the browser: a textbox on the map page (map notes) and on the run page
(run notes, with a playhead + **stamp timestamp** button, and a checkbox to make
the note apply to the whole map instead).

## The model

A note is `{note_id, scope, replay_md5?, t_map?, body, tags, created_at}`.

- **scope `map`** — applies to every attempt at the beatmap. With no `t_map` it
  is a general comment; with one it is "this spot in the map".
- **scope `run`** — belongs to one attempt (`replay_md5` is required). Useful
  for "this attempt felt off", which is not a property of the map.
- `t_map` is optional and in **map time**.

## Map time, and why it matters here

`t_map` is seconds on the `.osu`'s own clock — the time the editor shows, the
same on every attempt no matter the mods. A run's *row* clock is not that:

- For most exports the rows are already map time (`rows_scale` 1.0).
- For a modded run whose frames are in player time, `rows_scale` is 2/3 (DT),
  and a note stamped at row 667 ms is map 1.000 s.

`annotations.to_map_time(ms, time_base)` / `to_row_ms(t_map, time_base)` use
`time_base.rows_scale`; the web form stamps map time directly, so the chip reads
`2:14.312` and the note lands on the same objects on every attempt. (In this
author's corpus every DT export happens to store frames in map time, so
`rows_scale` is 1.0 there — the conversion is for the exports where it is not.
`tests/test_annotations.py` pins the 2/3 case.)

## Storage

Canonical: one JSON sidecar per beatmap, `out/annotations/<beatmap_md5>.json`.

```json
{
 "schema_version": 1,
 "beatmap_md5": "…",
 "notes": [
  {"note_id": "004ce67f", "scope": "map", "replay_md5": null,
   "t_map": 134.312, "body": "the second kiai is where the rhythm breaks",
   "tags": ["kiai"], "created_at": "2026-10-24T17:18:00+00:00",
   "updated_at": null}
 ]
}
```

Annotations are **authored**, so they are the one thing that is not a
projection: deleting `out/index.sqlite` must never lose one. The index mirrors
them (`annotations` table, keyed by `note_id`) purely so they can be queried;
every sweep replaces the mirror from the files. Writes are atomic
(temp file + rename), and a malformed sidecar reads as "no notes" rather than
crashing a page.

Hand-editing the file is allowed: a note with no `note_id` is given one on the
next load. Two writers at once (a browser save and a CLI `annotate add`) can
lose one of the two — there is no file lock, because there is one user.

## How the critic reads them

`coach` and `prompt` prepend a block before the metrics:

```
## The player's own notes (human annotations)
Written by the player about this map or play — treat them as context and a
hypothesis, not as measured fact. When a timestamp is given, check the objects
near it in the metrics.
- (map) 2:14.312 — the second kiai is where the rhythm breaks  [kiai]
- (this play) 0:12.000 — felt sloppy, cold hands
```

A directory-wide critique (`coach out/`) includes only the notes of the maps in
that set. The deterministic `report` does **not** read them — it is rule-based
by design; notes are context for the model, not evidence for the rules.

## Routes (web)

| route | method | body |
|---|---|---|
| `/map/<md5>/annotations` | POST | `body`, `t` (optional), `tag` |
| `/run/<id>/annotations` | POST | `body`, `t_map` (seconds, optional), `tag`, `scope=map` for map-wide |
| `/annotations/<note_id>/delete` | POST | `next` (a same-site path) |

`Form()` handling needs `python-multipart`, which is part of the `[web]` extra.
There is no CSRF token and no auth — same reasoning as the rest of the
frontend: it binds locally for one user. If you expose it, put it behind
something that authenticates.
