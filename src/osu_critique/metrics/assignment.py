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

# whiff causes: a press no object consumed, and why nothing took it
MASH = "mash"                  # no object within its 50-window at all
OFF_TARGET = "off_target"      # object in window, cursor not on the circle
SLIDER_HEAD = "slider_head"    # on-target press beside a slider head (head-only model)
LOST = "lost"                  # object in window, cursor on it, press left over
AFTER_END = "after_end"        # press after the last object's window

EDGE_GUARD_MS = 1.0            # see classify(): the stored frame clock is floored


def classify(error, w300, w100, w50, guard=EDGE_GUARD_MS):
    """OD-window judgement for a hit error in real ms.

    ``guard`` shrinks every window by that much, because a replay's frame clock
    is **floored to the millisecond**: the stored press time can be up to 1 ms
    earlier than the time the game actually judged, so an error we measure at the
    window edge belongs to a press the game saw outside it.

    The value is empirical and measured on the author's 55 stored replays: it is
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
          radius, search, hit_tol=1.0, guard=EDGE_GUARD_MS):
    """Resolve presses against objects in the game's order (osu! semantics).

    Objects are walked in time order; each takes the **first** press inside its
    window whose cursor is on the circle (spinners: any press inside the spin).
    A press is consumed at most once and never out of order, so a correctly
    timed earlier press can no longer be stolen by a later object, and a press
    cannot be handed backwards to an earlier one.

    Returns (results, detected, whiffs).
    """
    used = [False] * len(presses)
    results = []
    ptr = 0
    for o in objs:
        ptr = max(ptr, bisect.bisect_left(press_times, o["t"] - search))
        hi = bisect.bisect_right(press_times, o["t"] + search)
        taken = -1
        for j in range(ptr, hi):
            if used[j]:
                continue
            pt, _key = presses[j]
            if o["kind"] == "Spinner":
                if o["t"] <= pt <= o["end"]:
                    taken = j
                    break
            else:
                cx, cy = cursor_at(frames, times, pt)
                if math.hypot(cx - o["x"], cy - o["y"]) <= radius * hit_tol:
                    taken = j
                    break
        if taken < 0:
            results.append(_row(o, "miss"))
            continue
        used[taken] = True
        ptr = taken + 1
        pt, key = presses[taken]
        error = pt - o["t"]
        aim = (None if o["kind"] == "Spinner"
               else math.hypot(*_delta(cursor_at(frames, times, pt), o)))
        results.append(_row(o, classify(error, w300, w100, w50, guard), error,
                            aim, key, cursor_speed_at(frames, times, pt), pt))

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
    for j, (pt, _key) in enumerate(presses):
        if used[j]:
            continue
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
                inside = o["t"] <= pt <= o["end"]
            else:
                inside = abs(pt - o["t"]) + guard <= w50
            if inside and (near is None or abs(pt - o["t"]) < abs(pt - near["t"])):
                near = o
        if near is None:
            counts[MASH] += 1
            continue
        if near["kind"] == "Spinner":
            counts[LOST] += 1
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
