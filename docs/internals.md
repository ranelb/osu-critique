# How it works

1. **Parse** the `.osr`/`.osu` with the `slider` library.
2. **Frames** — replay actions sorted by time (some export tools emit
   out-of-order trailing frames; sorting is required for correct press
   detection and cursor interpolation).
3. **Judgement** — objects are walked in time order and each takes the first
   press inside its window whose cursor is on the circle, exactly as the game
   does: presses are consumed in order and never reused. The hit windows and the
   circle radius behind that gate come from the **mod-adjusted** difficulty
   (Hard Rock raises OD/AR/CS and reflects the playfield vertically, Easy halves
   them).
4. **Calibration** — the time scale is auto-selected (mod-based first, then
   unscaled) by the whole recorded count vector, not by the miss count alone.
   Some lazer exports and mod flags are misleading; this step disambiguates.
5. **Metrics** — hit/aim error, UR (also as a share of the 300-window), aim error
   against cursor speed, pattern buckets, regions, quarters, stream segments,
   whiffs by cause, tapping style, plus `failed_play` / `map_version_mismatch`
   flags and a `trust` block.
6. **Cursor arrival** — the frames are sampled around every note to measure where
   the cursor actually was: distance at the note, closest approach and its
   timing, the along/lateral split and the speed-conditioned ceiling curve
   (`metrics.aim_mode`). This needs no taps, so it is the whole aim picture on a
   Relax replay ([aim.md](aim.md)).
7. **Miss autopsy** — the shape classes, the press-time arrival margin, press
   vs arrival timing, per-leg heading and path efficiency, mid-travel presses and
   each miss with its own press and geometry (`metrics.autopsy`,
   [autopsy.md](autopsy.md)). Under Relax the tap-derived sections are
   reported as unavailable rather than as zero.
8. **Slider bodies** — every slider's curve (repeats included), ticks and tail
   are followed from the frames: how much of the body the cursor traced, which
   ticks it missed, whether the tail was dropped (`metrics.sliders`, and the
   `slider_*` fields in the per-object records).
9. **Records** — every object is written out with its rhythm snap, spacing, flow
   angle, strains and slider-body measurements (`out/<tag>_objects.json`): the
   schema later analyses read.
10. **Tiers** — `report` renders a deterministic critique from the JSON;
    `coach` upgrades it with one LLM API call (system prompt encodes the same
    critique framework; optional baseline + profile give it context).
