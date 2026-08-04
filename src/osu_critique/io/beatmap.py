"""Beatmap (.osu) loading, object building and mod/time scaling."""
from __future__ import annotations

import slider


def load_beatmap(map_path):
    return slider.Beatmap.from_path(map_path)


def mod_scale(r):
    """Map-time -> real-time multiplier (DT speeds up, HT slows down)."""
    if r.double_time:
        return 2.0 / 3.0
    if r.half_time:
        return 4.0 / 3.0
    return 1.0


def od_windows(od, scale):
    """Judgement half-windows in real ms for 300/100/50."""
    w300 = (80 - 6 * od) * scale
    w100 = (140 - 8 * od) * scale
    w50 = (200 - 10 * od) * scale
    return w300, w100, w50


def build_objects(bm, scale):
    """list of dicts: {t, end, x, y, kind} with t/end in real ms."""
    objs = []
    for o in bm.hit_objects():
        kind = type(o).__name__
        t = o.time.total_seconds() * 1000.0 * scale
        end = getattr(o, "end_time", o.time)
        end = end.total_seconds() * 1000.0 * scale
        pos = o.position
        objs.append({"t": t, "end": end, "x": pos.x, "y": pos.y, "kind": kind})
    objs.sort(key=lambda d: d["t"])
    return objs


def circle_radius(cs):
    """Circle radius in osu! pixels for a given circle size."""
    return slider.beatmap.circle_radius(cs)
