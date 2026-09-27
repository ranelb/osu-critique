# Per-object record schema

Every `osu-critique analyze` run writes two files beside each other:

| file | contents |
|---|---|
| `out/<tag>_metrics.json` | the per-play metrics (aggregates, trust block, per-object derived stats) |
| `out/<tag>_objects.json` | one record per hit object — the frozen schema below |

The per-object file is the spine every later analysis reads: pattern taxonomies,
strain-conditioned error, per-section breakdowns and cross-attempt comparisons
all query these rows rather than re-deriving them. Skip it with `--no-objects`.

## Document

```json
{
  "schema_version": 1,
  "tag": "overture",
  "player": "ran27",
  "map": "overture [nymphe's extreme]",
  "beatmap_md5": "413d503c3415f7626fbe5208a2d74c31",
  "mod_string": "NM",
  "counts_recorded": {"300": 161, "100": 18, "50": 0, "miss": 5},
  "counts_detected": {"300": 164, "100": 15, "50": 0, "miss": 5},
  "trust": {"...": "the same trust block as the metrics file"},
  "objects": [ {"i": 0, "...": "..."} ]
}
```

## Record fields (`objects[]`, in order)

| field | unit | meaning |
|---|---|---|
| `i` | index | object index, in play order |
| `t` | ms (real time) | object start time — DT/HT and the calibration scale applied |
| `kind` | — | `Circle`, `Slider` or `Spinner` |
| `end_t` | ms (real time) | slider/spinner end; equals `t` for circles |
| `x`, `y` | osu! px | object centre, Hard Rock reflected (`y -> 384 - y`) like lazer |
| `result` | — | `300` / `100` / `50` / `miss` as judged against the mod-adjusted OD windows |
| `error_ms` | ms | press time minus object time (negative = early); null on a miss |
| `aim_px` | osu! px | cursor distance from the centre at press time; null on a miss/spinner |
| `aim_r` | circle radii | `aim_px / radius` (the comparable form) |
| `key` | `A`/`B` | which tap button resolved the object |
| `cursor_speed` | px/ms | cursor speed at press time, from the bracketing frames |
| `spacing_r` | circle radii | distance to the previous object's centre |
| `pattern` | — | legacy spacing-only bucket: `dense` / `stream` / `jump` / `bigjump` |
| `snap` | quarter-beats | gap to the previous object in 1/4-beat units: `1.0` = 1/4 note, `2.0` = 1/2, `4.0` = 1/1; null without an uninherited timing point |
| `bpm` | BPM | the map's BPM at this object, as written in the .osu |
| `bpm_eff` | BPM | BPM as played (`bpm` scaled by DT/HT) — the rate the hands feel |
| `angle_deg` | degrees | turn between the incoming and outgoing movement vectors: `0` = straight (flow), `180` = full reversal (anti-flow); null for the first two objects |
| `strain_aim` | osu! strain | osu!'s own aim strain for this object, mod-aware; null if unavailable |
| `strain_speed` | osu! strain | osu!'s own speed strain for this object, mod-aware; null if unavailable |

## Rules

- **Additive only.** New fields may be appended; existing names, units and
  meanings do not change. A breaking change bumps `schema_version`.
- **Null means unknown, never zero.** A missing timing point, first-object
  spacing, a spinner's aim — all `null`; consumers must treat them as "no data",
  and must not silently drop the row.
- **Nothing here interprets the play.** Buckets, taxonomies and verdicts belong
  to the analysis layers above; this file is measurement only, so every later
  question can be asked of the same rows after the fact.
