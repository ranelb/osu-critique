# Validation, trust and limitations

## Validation and trust

`counts_detected` is judged to match the game's own recorded counts. Across the
author's 55 stored replays the judgement reproduces **14 plays exactly** and
drifts by a handful of objects on most of the rest (weighted L1 1470 over 55
plays).

The single biggest correction to the judgement was the **edge guard**
(`assignment.EDGE_GUARD_MS`, 1 ms): a replay's frame clock is floored to the
millisecond, so the stored press time can be up to 1 ms earlier than the time the
game judged, and an error measured *at* the window edge belongs to a press the
game saw outside it. Shrinking every window by that guard is the difference
between 1 and 14 plays reproduced exactly and halves the total drift; a 0.5 ms
guard reproduces 8, no guard 1. It is what made the slider-heavy plays agree: on
`MONTAGEM BATCHI` and `4ever (cut ver.)` the 300/100 split used to drift by 5-6
objects and now matches the game exactly.

Even with it, a play can be honest about what it cannot know. `trust` carries
`count_deltas` (the per-count difference), `within_tolerance` (miss within
max(3, 2% of judged objects); the whole vector within max(5, 5%)), `notes` (why a
play is not trustworthy: a failed play, a `map_version_mismatch`, relax) and the
calibration that was chosen. The console summary and the deterministic report
state it before anything else is concluded. On a small number of plays the miss
count still drifts (a dropped slider end is the remaining suspect); those stay
`trustworthy: false` rather than being smoothed over.

## Edge cases and limitations

- **Relax replays**: the game auto-hits from cursor position, so press-time aim,
  whiffs and tapping are the game's, not the player's — read `aim_mode` (cursor
  arrival) instead. Timing there is cursor arrival, not taps.
- **Sliders are judged by their head**: the .osr counts themselves exclude ticks
  (the four counts sum to the map's object count). The body, its ticks and its
  tail are *measured* (`metrics.sliders`, the `slider_*` record fields) but do
  not change the judgement: on these replays the game counts a slider the player
  cut as a 300 anyway (degrading cut sliders makes 15 of 19 slider-heavy plays
  worse). Presses consumed by a slider body rather than its head appear as
  `whiffs.slider_head`.
- **Mods**: Hard Rock (OD/AR ×1.4, CS ×1.3, playfield reflected vertically) and
  Easy are applied to windows and geometry; DT/HT go through the time scale.
  HD/FL/NF change nothing measurable here. Relax/AutoPilot plays are flagged and
  judged from the cursor-arrival block.
- **Lazer export time convention**: some exports store frames in map-time, not
  real-time; calibration handles it automatically, and when the mod flag and the
  frames disagree the run reports both clocks (`metrics.time_base`) instead of
  quoting one silently.
- **`map_version_mismatch`**: replay ends well before the map's last object —
  analysis is only reliable up to the replay end.
- **Mod flags**: a replay may claim DT/HT while its frames are at map-time
  (lazer export quirk); the scale calibration picks the consistent interpretation.
