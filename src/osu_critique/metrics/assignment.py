"""The core assignment engine: resolve key presses against hit objects.

osu! judges a press against the **earliest object still awaiting judgement**, in
press order -- it never goes looking for the closest press to each object. The
first implementation here did exactly that (per-object nearest press inside a
+/-250 ms search window), which lets an object steal a press belonging to a
later object and lets a later object claim an earlier press: on messy,
slider-heavy plays that cascades fabricated misses (measured on a real replay
the game scored with 62 misses, the nearest-press rule detected 117; consuming
presses in the game's order detects 66).

``judge`` is the pipeline's engine. ``assign_nearest`` is the old rule, kept as
a reference so the difference stays visible and testable.
"""
from __future__ import annotations

import bisect
import math

from ..io.replay import cursor_at
from .spinner import judge_spinner

# whiff causes: a press no object consumed, and why nothing took it
MASH = "mash"                  # no object within its 50-window at all
OFF_TARGET = "off_target"      # object in window, cursor not on the circle
SLIDER_HEAD = "slider_head"    # on-target press beside a slider head (head-only model)
LOST = "lost"                  # object in window, cursor on it, press left over
AFTER_END = "after_end"        # press after the last object's window

EDGE_GUARD_MS = 1.0            # see classify(): the stored frame clock is floored
MISS_WINDOW_MS = 400.0         # lazer's miss window: an earlier press is a consumed miss


def classify(error, w300, w100, w50, guard=EDGE_GUARD_MS):
    """OD-window judgement for a hit error in real ms.

    ``guard`` shrinks every window by that much, because a replay's frame clock
    is **floored to the millisecond**: the stored press time can be up to 1 ms
    earlier than the time the game actually judged, so an error we measure at the
    window edge belongs to a press the game saw outside it.

    The value is empirical and measured on a 55-replay reference corpus: it is
    the difference between 1 and 14 plays whose counts the tool reproduces
    *exactly*, and it halves the total drift (weighted L1 1943 -> 1470). The same
    evidence rejects a 0.5 ms guard (8 exact) and no guard at all (1 exact). See
    README "Validation and trust".
    """
    ae = abs(error)
    if ae + guard <= w300:
        return "300"
    if ae + guard <= w100:
        return "100"
    if ae + guard <= w50:
        return "50"
    return "miss"


def cursor_speed_at(frames, times, t):
    """Cursor speed (px/ms) at time t, from the bracketing frames."""
    i = bisect.bisect_right(times, t)
    if 0 < i < len(frames) and times[i] > times[i - 1]:
        return math.hypot(frames[i][1] - frames[i - 1][1],
                          frames[i][2] - frames[i - 1][2]) / (times[i] - times[i - 1])
    return None


def _delta(cursor, o):
    return (cursor[0] - o["x"], cursor[1] - o["y"])


def _row(o, result, error=None, aim=None, key=None, speed=None, press_t=None):
    return {**o, "result": result, "error": error, "aim": aim, "key": key,
            "cursor_speed": speed, "press_t": press_t}


def judge(objs, frames, times, presses, press_times, w300, w100, w50,
          radius, search, hit_tol=1.0, guard=EDGE_GUARD_MS, spinner_od=None,
          scale=1.0):
    """Resolve presses against objects the way the game does (lazer semantics).

    The walk is **press-driven**, in time order: objects whose 50-window has
    closed are missed first, then the press goes to the earliest unjudged
    object whose circle the cursor is on and that the **note lock** lets it
    hit. A press is consumed at most once.

    * Note lock: an object cannot be hit while the object before it is still
      unjudged and the press is earlier than that object's start time
      (lazer's ``StartTimeOrderedHitPolicy``). A locked press falls through to
      the next object under the cursor, and is whiffed if there is none.
    * Early presses: a press on an object inside its miss window (``search``,
      ``MISS_WINDOW_MS`` times the clock ``scale``) but outside the 50-window
      is a **miss that consumes the press**, not a no-op.

    The first implementation walked objects instead of presses, so the lock did
    not exist and a later object could not take a press the earlier object's
    own (later) press had "passed": exact count matches on the 3462-play
    reference corpus went 68.3 % -> 85.9 % (docs/ROADMAP.md, judge fidelity).

    Spinners take no press and are not timed: they are rated by how far the
    cursor turned (``metrics/spinner.py``), which needs the mod-adjusted
    ``spinner_od`` and the time ``scale`` of the frames' clock. Without
    ``spinner_od`` a spinner is rated "300" (completion unknown), never timed
    through the circle windows.

    Returns (results, detected, whiffs).
    """
    used = [False] * len(presses)
    results = [None] * len(objs)
    tapped = []                       # indices into objs, time order
    for i, o in enumerate(objs):
        if o["kind"] == "Spinner":
            if spinner_od is None:
                verdict, progress, required = "300", None, None
            else:
                verdict, progress, required = judge_spinner(frames, times, o,
                                                            spinner_od, scale)
            row = _row(o, verdict)
            row["spin_progress"] = progress
            row["spin_required"] = required
            results[i] = row
        else:
            tapped.append(i)

    n = len(tapped)
    judged = [False] * n
    first = 0

    def settle(k, result, press=None):
        judged[k] = True
        o = objs[tapped[k]]
        if press is None:
            results[tapped[k]] = _row(o, "miss")
            return
        pt, key = presses[press]
        used[press] = True
        cx, cy = cursor_at(frames, times, pt)
        results[tapped[k]] = _row(o, result, pt - o["t"],
                                  math.hypot(cx - o["x"], cy - o["y"]), key,
                                  cursor_speed_at(frames, times, pt), pt)

    for j, (pt, _key) in enumerate(presses):
        k = first
        while k < n and pt - objs[tapped[k]]["t"] + guard > w50:
            if not judged[k]:
                settle(k, "miss")     # window closed with nothing taking it
            k += 1
        first = k
        while first < n and judged[first]:
            first += 1
        cx, cy = cursor_at(frames, times, pt)
        k = first
        while k < n and objs[tapped[k]]["t"] - search <= pt:
            o = objs[tapped[k]]
            if judged[k] or math.hypot(cx - o["x"], cy - o["y"]) > radius * hit_tol:
                k += 1
                continue
            if k > 0 and not judged[k - 1] and pt < objs[tapped[k - 1]]["t"]:
                k += 1                # note lock: the previous object is not over
                continue
            settle(k, classify(pt - o["t"], w300, w100, w50, guard), j)
            break

    for k in range(n):
        if not judged[k]:
            settle(k, "miss")

    detected = {"300": 0, "100": 0, "50": 0, "miss": 0}
    for x in results:
        detected[x["result"]] += 1
    return results, detected, classify_whiffs(objs, frames, times, presses, used,
                                              radius, w50, guard)


def classify_whiffs(objs, frames, times, presses, used, radius, w50,
                    guard=EDGE_GUARD_MS):
    """Explain every unconsumed press (see the cause constants)."""
    counts = {MASH: 0, OFF_TARGET: 0, SLIDER_HEAD: 0, LOST: 0, AFTER_END: 0}
    off_r = []
    obj_t = [o["t"] for o in objs]
    last_t = objs[-1]["t"] if objs else 0.0
    spin = [o for o in objs if o["kind"] == "Spinner"]
    for j, (pt, _key) in enumerate(presses):
        if used[j]:
            continue
        if any(o["kind"] == "Spinner" and o["t"] <= pt <= o["end"] for o in spin):
            continue                      # spinning is not tapping
        if not objs or pt > last_t + w50 + guard:
            counts[AFTER_END] += 1
            continue
        i = bisect.bisect_left(obj_t, pt)
        near = None
        for k in (i - 1, i):
            if not 0 <= k < len(objs):
                continue
            o = objs[k]
            if o["kind"] == "Spinner":
                continue
            inside = abs(pt - o["t"]) + guard <= w50
            if inside and (near is None or abs(pt - o["t"]) < abs(pt - near["t"])):
                near = o
        if near is None:
            counts[MASH] += 1
            continue
        d = math.hypot(*_delta(cursor_at(frames, times, pt), near))
        if d > radius:
            counts[OFF_TARGET] += 1
            off_r.append(d / radius)
        elif near["kind"] == "Slider":
            counts[SLIDER_HEAD] += 1
        else:
            counts[LOST] += 1
    n = sum(counts.values())
    return {"n": n, "rate": n / max(1, len(presses)), **counts,
            "off_target_mean_r": (sum(off_r) / len(off_r)) if off_r else None}


def assign_nearest(objs, frames, times, presses, press_times, w300, w100, w50,
                   radius, search, hit_tol=1.0, guard=EDGE_GUARD_MS):
    """Deprecated reference: per-object nearest press. Kept for comparison only."""
    used = set()
    results = []
    for o in objs:
        lo = bisect.bisect_left(press_times, o["t"] - search)
        hi = bisect.bisect_right(press_times, o["t"] + search)
        best_i, best_d = None, None
        for j in range(lo, hi):
            if j in used:
                continue
            pt, _key = presses[j]
            if o["kind"] == "Spinner":
                if not (o["t"] <= pt <= o["end"]):
                    continue
                d = abs(pt - o["t"])
            else:
                d = abs(pt - o["t"])
                cx, cy = cursor_at(frames, times, pt)
                if math.hypot(cx - o["x"], cy - o["y"]) > radius * hit_tol:
                    continue
            if best_d is None or d < best_d:
                best_d, best_i = d, j
        if best_i is None:
            results.append(_row(o, "miss"))
            continue
        used.add(best_i)
        pt, key = presses[best_i]
        error = pt - o["t"]
        aim = (None if o["kind"] == "Spinner"
               else math.hypot(*_delta(cursor_at(frames, times, pt), o)))
        results.append(_row(o, classify(error, w300, w100, w50, guard), error,
                            aim, key, cursor_speed_at(frames, times, pt), pt))
    detected = {"300": 0, "100": 0, "50": 0, "miss": 0}
    for x in results:
        detected[x["result"]] += 1
    return results, detected, len(presses) - len(used)


# backwards-compatible alias for the old name
assign = judge
