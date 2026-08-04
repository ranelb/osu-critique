"""The core assignment engine: match key presses to hit objects."""
from __future__ import annotations

import bisect
import math

from ..io.replay import cursor_at


def classify(error, w300, w100, w50):
    ae = abs(error)
    if ae <= w300:
        return "300"
    if ae <= w100:
        return "100"
    if ae <= w50:
        return "50"
    return "miss"


def assign(objs, frames, times, presses, press_times, w300, w100, w50,
           radius, search, hit_tol=1.0):
    """Greedy nearest-press assignment per object.

    A press only counts for a non-spinner object if the cursor is within
    ``hit_tol * radius`` of the object centre at press time (mirrors osu!'s
    own aim requirement). Returns (results, detected, whiffed).
    """
    used = set()
    results = []
    for idx, o in enumerate(objs):
        lo = bisect.bisect_left(press_times, o["t"] - search)
        hi = bisect.bisect_right(press_times, o["t"] + search)
        best_i, best_d = None, None
        for j in range(lo, hi):
            if j in used:
                continue
            pt, key = presses[j]
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
            results.append({**o, "result": "miss", "error": None,
                            "aim": None, "key": None, "cursor_speed": None})
            continue
        used.add(best_i)
        pt, key = presses[best_i]
        error = pt - o["t"]
        res = classify(error, w300, w100, w50)
        cx, cy = cursor_at(frames, times, pt)
        aim = math.hypot(cx - o["x"], cy - o["y"]) if o["kind"] != "Spinner" else None
        sp = None
        i = bisect.bisect_right(times, pt)
        if 0 < i < len(frames) and times[i] > times[i - 1]:
            sp = math.hypot(frames[i][1] - frames[i - 1][1],
                            frames[i][2] - frames[i - 1][2]) / (times[i] - times[i - 1])
        results.append({**o, "result": res, "error": error, "aim": aim,
                        "key": key, "cursor_speed": sp})

    whiffed = len(presses) - len(used)
    detected = {"300": 0, "100": 0, "50": 0, "miss": 0}
    for x in results:
        detected[x["result"]] += 1
    return results, detected, whiffed
