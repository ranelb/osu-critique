# Validation, trust and limitations

## Validation and trust

`counts_detected` is judged to match the game's own recorded counts. The
original 55-replay reference corpus reproduced 14 plays exactly (weighted L1
1470); it has since grown to 3462 non-relax plays over 474 maps, and
`scripts/judge_drift.py` on that corpus (2026-11-28) reproduces **2363 plays
exactly (68.3 %), mean weighted L1 2.83**. Split by what the map contains:

| slice | plays | exact | mean L1 |
|---|---|---|---|
| no spinner | 1976 | 74.1 % | 1.77 |
| has spinner | 1486 | 60.4 % | 4.22 |

**Spinners** are rated by spin completion (`metrics/spinner.py`), not through the
circle OD windows; before that the spinner slice sat at 2.8 % exact (mean L1
7.24) and the whole corpus at 43.5 % (4.12). The rotation model is approximate
(no rate cap, no key check, no per-spinner ground truth); it rates nearly every
spinner 300, which is what the game does. The remaining drift on non-spinner
plays is one-directional (the judge over-detects misses) and grows with length
and miss count; it is not yet explained. Pauses and slider heads/tails are the
suspects, not isolated. 88 of the corpus' replays are lazer exports slider
0.8.4 cannot parse (float life-bar offsets) and are not measured.

The single biggest correction to the judgement was the **edge guard**
(`assignment.EDGE_GUARD_MS`, 1 ms): a replay's frame clock is floored to the
millisecond, so the stored press time can be up to 1 ms earlier than the time the
game judged, and an error measured *at* the window edge belongs to a press the
game saw outside it. Shrinking every window by that guard is the difference
between 1 and 14 plays reproduced exactly and halves the total drift; a 0.5 ms
guard reproduces 8, no guard 1. It is what made the slider-heavy plays agree: on
the slider-heavy reference plays the 300/100 split used to drift by 5-6 objects
and now matches the game exactly.

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
