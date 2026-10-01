# The miss autopsy

`metrics["autopsy"]` answers "why *these* notes" — the per-play block that turns
the shape classes, the arrival margin and the per-leg geometry from a throwaway
script into part of the pipeline. Computed for every `analyze` run (skip it with
`--no-autopsy`), printed by the deterministic report as a `## Miss autopsy`
section, and drawn as `out/<tag>_windows.png` with `--charts` (the worst arrival
stretches: the pattern, the cursor path coloured by time, and where the cursor
was when each note was due).

The point of most of it is a **contrast**: a weakness present in one shape class
and absent in another names the thing to practise, where an absolute rate just
names the most common bucket.

## shapes — where the notes that were not 300 live

Every object's 5-note window (the object, two either side) is classified by its
turn angles:

| class | rule |
|---|---|
| `near-reversal chain` | all but one of the window's turns are > 120° |
| `cornered (box)` | at least two turns of 55–120° |
| `flow (arc/line)` | every turn is < 55° |
| `mixed` | anything else |

Each class carries `n`, its `share` of the map, the off-300 count and rate, the
mean distance at the note (from the aim block) and the mean jump size. A rate is
only marked `reported` from `min_n` (10) windows; below that it is noise with a
number attached. Turn calculations need the two objects before a turn, so the
first two and last two objects have no window.

## arrival_margin_r — how close to the rim the presses land

The distance from the object centre at **press time**, in circle radii, with its
median, p90/p95/p99, max and the share pressed beyond 0.8 r. This is the "does he
live on the rim" distribution: a player whose p99 sits at 1.00 r is one bad frame
from a miss on every note.

## press_vs_arrival_ms — the two clocks

Per object, the press offset minus the cursor's closest-approach offset. Negative
means the button went down **while the cursor was still travelling**. A negative
median with a healthy `aim_mode.closest_approach_r` is the arrival-timing
mechanism stated as a single number, rather than inferred from two averages.

## legs — is it reading, or is it timing?

For every leg at least 1.5 circle radii long (shorter legs are correction inside
the circle, not travel):

- **heading error** — the angle between the direction the pattern requires and
  the direction the cursor actually took between the two notes;
- **path efficiency** — straight-line distance ÷ distance actually walked.

Clean headings *and* high efficiency mean the cursor goes where the pattern asks
and the failure is timing or speed. High headings or a low efficiency mean a
reading or path-finding problem — a different fix. (A symmetric detour keeps the
heading clean and shows up only in efficiency.)

## stutter — presses made mid-travel

Presses more than 40 ms before the coming object while the cursor is still more
than 2.5 r away from it. A few percent of presses is normal play; a rising share
is the hand pressing ahead of the arm.

## misses — the misses themselves

Each miss with the nearest press in its 50-window (consumed or not), that press's
own cursor distance, the distance at the note instant, the local jump size and
turn, and the speed the jump demanded. Worst (furthest at the note) first, capped
at 25 rows; `n` is the true total. Under Relax there are no presses, so the press
columns are absent — the geometry stays.

## Reference numbers

On the author's replays (docs/ROADMAP.md item 2):

| | near-reversal | cornered | misses | heading error |
|---|---|---|---|---|
| MONTAGEM BATCHI | 17.5 % off 300 (n=143) | 0 % (n=14) | 1.32 / 1.30 / 1.07 r at the note, presses +5 / +2 / −3 ms | median 2°, p90 8°, max 14° |
| 4ever | 9.1 % (n=165) | 0 % (n=9) | 1.20 r (press −9 ms, aim 1.26 r) and 0.98 r (press +16 ms, aim 1.07 r) | median 2°, p90 6°, max 11° |

`tests/test_autopsy.py` pins the helpers on synthetic frames and checks these
numbers when `OSU_TEST_MONTAGEM_REPLAY` / `_MAP` and `OSU_TEST_4EVER_REPLAY` /
`_MAP` are set.
