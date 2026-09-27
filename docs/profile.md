# The map profile

`metrics["profile"]` describes **what the map asked for**, as opposed to the
per-play aggregates, which describe how the play went. It is built from the
per-object records (`docs/object_schema.md`) plus the map's own slider geometry,
so no extra inputs are needed. It is printed by `analyze`, included in the
deterministic `report`, and handed to the coach.

## rate — how fast the map actually is

| field | meaning |
|---|---|
| `effective_bpm` | map BPM scaled by the player's mods (DT x1.5, HT x2/3): the rate the hands feel. It uses the mod flag, not the calibrated scale, so a rejected DT flag still reports 383, not 255 |
| `note_gap_ms` | gap to the previous object in **real** ms: p10 / median / p90 |
| `notes_per_second` | mean over the play, and the rate implied by the median gap |
| `gap_vs_300_window` | the tightest / median gap as a multiple of the 300-window |
| `snap_mix` | how many objects arrive at each divisor (1/4, 1/2, 1/1), or at an explicit beat count when the gap is slower than a beat (2 beats, 1.5 beats) |

Rhythm claims are meaningless without the gap: "1/8 snap" is 39 ms per note on a
382 BPM DT map and 118 ms on a 255 BPM one.

Every millisecond in the block is in the **player** time base: when calibration rejects a misleading mod flag the rows are converted back, so a DT replay whose frames are in map time reports 78 ms note gaps against a 29 ms 300-window, not 117 against 44. The divisor is derived as `4 / snap`
(snap is stored in quarter-beats); gaps slower than one beat are labelled by
their beat count instead of pretending to be a divisor.

## composition — the pattern families

A family is `<kind>_<divisor>_<spacing>`: `circle_1/2_jump` is a circle arriving
half a beat after the previous object at more than 4 circle radii of spacing —
"1/2 jumps"; `slider_1/4_dense` is a slider half a quarter-note after the
previous object at ≤2r — a dense slider chain. Each entry carries `n`, `share`
of the map, `non300` / `non300_rate`, `mean_err_ms`, `std_err_ms` and
`mean_aim_r`, with `reported: false` below 10 objects so nothing is concluded
from a handful of notes.

`sliders` characterises the map's sliders independently: count, share of long
paths (≥100 px, i.e. a real path to trace), length percentiles and the **cursor
speed the slider demands** (`pixel_length ÷ duration per repeat`) in px/ms.

## stamina — the load over time

Notes per second in short bins, the peak and mean rate, seconds spent above
6 notes/s, the **longest sustained run** (notes and seconds), and the breaks
(bins below 1 note/s). This is what makes "stamina heavy" checkable instead of
an impression.

## chains — sustained tapping

Maximal runs of ≥4 consecutive objects whose gaps stay within ±35% of each other
and below 250 ms — rhythm continuity, not "4 circles with ≤4r spacing" (which
calls 1/2 filler runs streams while ignoring slider-interleaved speed material).
Reports the number of runs, their notes, the hit rate **by position**
(`1-4`, `5-8`, `9-12`, `13+` — where does sustained tapping break?) and the five
worst runs with their timestamps.

## timing_by_family — bias is not one number

Signed bias, p10/p90 and hit rate per family (n ≥ 10). A single global bias can
be the average of arriving 20 ms late on jumps and tapping 20 ms early on slow
notes — two different fixes.

## context — what came before

Hit rate after a circle, a short slider, a long slider (>60% of the gap) or a
spinner.

## primary target

`primary_target()` picks the family to work on: it must have at least
`max(20, 3% of the map)` objects and a hit rate at least 1.5× worse than the play
as a whole. Absolute counts are never used — they just name the most numerous
bucket.
