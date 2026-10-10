# How it breaks down (`metrics["breakdown"]`, `osu-critique breakdown`)

`metrics["breakdown"]` says **how** a play fails, not just where. The miss
autopsy and the pattern table say which objects and which shapes produced the
misses; this block puts a mechanism underneath them:

- **the speed cliff** — miss rate per *required cursor speed*: where "safe"
  turns into "explodes".
- **reversal x spacing** — sharp turns (>= 150°) split by whether the jump is
  wide (>= 6r), against flow windows (< 60°) of the same width.
- **cascades** — runs of consecutive-object misses (accumulation), never the
  isolated whiff.
- **the worst ramp** — the densest cluster of misses, with the spacing and
  required-speed range it spans.

It is computed for every `analyze` run and stored in the metrics JSON; print it
standalone with `osu-critique breakdown out/<tag>_metrics.json` (add `--json`
for the raw block). On metrics files written before the block existed it
recomputes from the sibling `<tag>_objects.json`.

## How the speed is measured

The **required cursor speed** for an object is recomputed here as

    dist(previous object -> this object) / dt          # px/ms

from the object's `x` / `y` / `t`. It does **not** read
`objects[].cursor_speed`, because that field is null on a no-press miss — binning
on it would silently hide exactly the misses the block is about (this produced a
wrong "1.8% miss" cliff before it was caught).

Gaps longer than 1500 ms are treated as breaks, not travel, and skipped; the
first object has no predecessor and no required speed.

## Fields

| field | meaning |
|---|---|
| `speed_bins` | miss rate per required-speed bin (`n`, `miss`, `rate`), each bin n-gated by being non-empty |
| `knee` | upper edge of the fastest bin still under 10% miss (n >= 10) — the last safe speed |
| `cliff` | lower edge of the first bin at/above 25% miss (n >= 5) — where it explodes |
| `reversal` | miss rate for `sharp>=150deg` split at 6r spacing, plus `flow<60deg, spacing>=6r` |
| `cascades` | maximal runs of >= 2 consecutive misses (`start_i`, `end_i`, `n`, `t0`, `t1`), longest first |
| `ramp` | the window of 28 travels with the most misses (then the fastest): its time span, miss count, spacing and required-speed range, and the object ids |

## Reading it

- **A cliff with a knee far below your usual speed** means you are already past
  your safe ceiling on this map, and the misses are a capacity problem, not a
  reading one. A cliff only at the very top means the map is mostly within range.
- **`reversal` sharp-and-wide vs sharp-and-tight** separates "I cannot turn at
  all" from "I cannot turn far"; a big gap between them is about jump length,
  not about the reversal itself.
- **Cascades, not misses, are the thing to look at.** One whiff is noise; a run
  of them is the map (or the player) accumulating error. The ramp points at
  where.

Nothing here judges the play: the block is measurement and carries its own `n`
per bin. Under `trust=false` the exact rates are approximate — read the
mechanism (which bin, which bucket), not the third decimal.
