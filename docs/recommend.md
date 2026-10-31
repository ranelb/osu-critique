# Recommendations

```sh
osu-critique recommend [--limit 6] [--player NAME] [--stretch 0.5]
                       [--bucket new|improver|maintain ...] [--skills] [--json]
osu-critique blacklist add --map <md5> | --set <BeatmapSetID>
osu-critique blacklist rm  --map <md5> | --set <BeatmapSetID>
osu-critique blacklist list [--json]
```

`recommend` answers one question: **what should I play next, and why that map**.
It needs two derived things — `osu-critique index` (the runs) and
`osu-critique library scan` (the maps) — and no network, no key, no model. The
whole call takes ~0.4 s on a 3 400-run / 5 600-map corpus.

The dashboard calls the same function; `recommend --json` is the testable
surface and the contract.

## The evidence: weaknesses

A weakness is measured **on map material**, not on per-object buckets. That is
the one deliberate unit change from `metrics/attempts` and
`metrics/profile.primary_target`: those describe one play's objects, while a
recommendation has to filter the *library*, and a never-played map only has
map-side features. Using the same axis on both sides means there is no
"family → feature" translation that can quietly lie.

- **Outcome: the miss rate** (misses / objects), not accuracy. Accuracy is
  saturated by a handful of 100s on a short map; a miss is unambiguous, and it
  is what a player wants fewer of.
- **Band-corrected.** Each run's miss rate is compared with *your own* median
  miss rate in the same half-star band. Without this, "you miss more on
  stream-heavy maps" mostly means "stream-heavy maps in your library are
  harder", which is not a skill.
- **Median split per dimension.** Your plays are split at the dimension's median
  into two halves; the halves' band-corrected miss rates are compared. The split
  point and both halves are printed — a verdict without a denominator is not
  evidence.
- **Dimensions:** sustained density (`sustained_nps`), stream share, jump
  spacing (jump + bigjump), sharp reversals (`anti_flow_share`), slider density.
- **Gates:** ≥20 runs per side, ≥0.5 pp difference in excess miss rate, and an
  excess ratio ≥1.5 (with a 0.05 pp floor so a near-baseline good half cannot
  make a small difference look infinite). Top 3, strongest first, with `n`
  quoted. Nothing is claimed from n < 10.
- **Correlated dimensions collapse.** If two dimensions correlate at |r| ≥ 0.9
  over your runs (e.g. "few streams" and "few sliders" are both "spaced
  circles"), only the stronger is reported.
- **Window:** the last 90 days, or the whole corpus when that is under 60 runs.
  The window used is in the output.
- **Relax/Autopilot is not evidence.** The game taps in RX/AP, so a miss there
  says nothing about your tapping. Those runs are counted and excluded — and a
  map played *only* in Relax is not offered as "never played"; it is counted as
  `relax_only` and left alone.

With no weakness that clears the gate, `basis` is `difficulty-only` and the
cards say so: they are difficulty-appropriate maps, and the page does not
pretend otherwise.

## Buckets

A map is in exactly one bucket, or in none.

| bucket | evidence |
|---|---|
| `new` | you have never played it |
| `improver` | ≥2 attempts, and the latest is ≥3 pp of accuracy below the median of your runs in the same 0.25-star band, or failed. The card carries the proof: **best here, that band median, the last attempt** |
| `maintain` | at or above the band median, last played ≥30 days ago |

Anything else (played recently, or played badly but recently and well enough) is
`played_other`: no recommendation. A band median needs ≥5 runs to exist;
below that a map is ineligible rather than compared with noise. `maintain` uses
the same 30-day number as the dashboard window, so "stale" and "this month"
cannot disagree.

## Candidate gates

Star mode only (`mode == 0`), drain 0:40–4:30, ≥120 objects, a star rating
(no `sr` means "cannot rank this map", never zero), and within **±1.0★** of
your comfort rating (the median SR of your window). One difficulty per
beatmapset per list, blacklists applied.

## Scoring

```
score = (0.5 + similarity) × difficulty_fit × bucket_term
```

- **similarity** — how far the map sits on the *bad* side of your worst-matching
  weakness, as a percentile within your own played distribution, scaled by that
  weakness's weight (gap relative to the strongest). `0.5 +` keeps a map that
  matches nothing from scoring zero.
- **difficulty_fit** — a Gaussian centred at `comfort + 0.6·stretch`, with
  `σ = 0.35 + 0.5·stretch`. `--stretch` is the only difficulty knob: 0 aims at
  your comfort rating, 1 at a real step above it.
- **bucket_term** — `new` 1.0; `improver` up to 2.0, scaled by how far below the
  band median the last attempt was; `maintain` 0.6→1.0 with staleness.

Selection is deterministic: score descending, md5 ascending on ties. The three
buckets are then **interleaved** (`new`, `improver`, `maintain`, repeat) instead
of letting one score scale win outright — six improvers in a row is not a plan.
Order inside a bucket stays score order. `--bucket` restricts the list to one
kind.

No timestamps in the output and no randomness: the same corpus gives byte-equal
JSON, which is what the tests assert.

## Why-lines are written by the code

Every card states its own evidence, from the numbers it was scored with:

```
3.1★ · 132 BPM · 2:05 · jump spacing
· trains sharp reversals — you miss 6.4% on that half vs 4.4% on the other (n=588/590)
· improver: best 96.0% over 6 runs, this band's median 94.7%, last attempt 80.0%
```

The wording is a template in `recommend.py`. No model is involved, so the card
cannot say something the numbers do not.

## Blacklist

`out/blacklist.json`, authored like annotations and stored critiques (the index
mirrors it into the `blacklist` table; deleting the DB never un-blocks a map):

```json
{ "schema_version": 1, "maps": ["<beatmap md5>"], "sets": [1234567], "updated": "..." }
```

`maps` blocks one difficulty, `sets` blocks every difficulty of a beatmapset
(including ones imported later — matching is done on the candidate's `set_id`,
nothing is expanded up front). `recommend --no-blacklist` exists for debugging
only.

## Limits

- A band median is a coarse baseline: it needs 5 runs, and it is a median, not a
  model. It is quoted on every improver card so the comparison is visible.
- Maps that are no longer on disk (or that the pinned `slider` cannot parse)
  cannot be attached to a material; runs on them are counted as `unmapped_runs`
  and ignored.
- The skill profile is about *your* corpus. A player with 50 runs will usually
  get `difficulty-only` — correctly: there is not enough evidence for more.
