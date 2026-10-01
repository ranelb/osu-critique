# The aim block (cursor arrival)

`metrics["aim_mode"]` describes **what the hand did with the cursor**, sampled
from the replay frames rather than from the taps. Every other aim number in the
package is taken at *press* time; this one follows the cursor path itself.

It exists because press-time aim answers the wrong question in three situations:

- **Relax / Autopilot** — the game taps, so "distance at press time" measures the
  game. Only the cursor is left, and it is the cleanest aim measurement there is.
- **Late or dropped taps** — a press can land while the cursor is still
  travelling, so press-time distance folds arrival *timing* into arrival
  *accuracy*.
- **Everywhere else** — at press time we never look at where the cursor was a
  moment later, which is where the miss actually happened.

It is computed for every `analyze` run (skip it with `--no-aim`) and rendered
into `out/<tag>_aim.png` with `--charts`: six panels — the ceiling, arrival
timing, the along/lateral target frame, drift through the play, where on the
playfield, and "there, just not then".

## How it is measured

For every non-spinner object the cursor is sampled every 3 ms from 320 ms before
to 320 ms after the note (`window_ms` / `sample_ms` are echoed in the block so
the "reached at all" claim stays auditable), and the arrival is summarised:

| field | meaning |
|---|---|
| `distance_at_note_r` | cursor distance from the centre **at the note instant** (mean / median / p90, and the share inside the circle) |
| `closest_approach_r` | best approach within the window, and how many notes the cursor never entered |
| `peak_offset_ms` | when that best approach happens, in ms versus the note (median, p10/p90, % late > 20 ms, % early < −20 ms) |
| `window_entry_ms` | when the cursor first enters the circle (median, p10/p90, never-entered count) |
| `reached_not_on_time` | notes reached inside the window but **not** at the note instant (`closest<=1r` and `distance_at_note>1r`) |
| `error_shape` | the split along the travel axis (`short_pct` / `past_pct`, with the along percentiles) and the lateral spread |
| `ceiling` | distance at the note binned by the **cursor speed the jump demands** (`gap ÷ dt`, px/ms), n-gated, with its own peak offset |
| `by_jump_distance` | distance at the note binned by jump length in circle radii |
| `over_time` | distance at the note in six equal time bins — stamina drift |

Nothing in the rows judges the play: a note does not have to be a miss to show up
as a late arrival. The block is measurement, and it carries its own `n`.

## Reading it

- **`distance_at_note_r` much worse than `closest_approach_r` = a timing
  problem, not a precision problem.** If the cursor gets there (small
  `closest_approach_r`) but `peak_offset_ms` is positive and
  `reached_not_on_time` is large, the hand arrives late; the fix is timing, not
  control.
- **`error_shape.along_r` is signed.** Mostly negative means the cursor stops
  short; positive means it overshoots; a wide `lateral_r` is a direction error
  rather than a distance one.
- **The ceiling is the real aim verdict.** A static "0.30–0.45 r is good" hides
  that a 9 r flick and a 1 r nudge are different tasks. Read `ceiling` left to
  right: where the mean leaves 1 r is the speed at which aim stops holding.
- **Under Relax, this is the whole analysis.** Press-time aim and timing are the
  game's, and the whiff/tapping blocks are meaningless.

## Reference numbers

On the author's Relax reference replay (665 objects, AR10/OD10), the block
reproduces: 0.72 r mean at the note, 0.26 r median closest approach, median peak
+10 ms, 16.8 % reached-not-on-time, and a ceiling of 0.47 r at ≤1 px/ms rising to
1.19 r above 3 px/ms. `tests/test_aim.py` pins a synthetic RX fixture with a
known cursor path exactly, and checks the reference numbers when
`OSU_TEST_RX_REPLAY` / `OSU_TEST_RX_MAP` are set.
