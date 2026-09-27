"""Beatmap (.osu) loading, object building and mod/time scaling.

Mods that change geometry or judgement are applied here rather than ignored:
the hit windows come from the mod-adjusted OD (``od_for``/``cs_for``) and Hard
Rock reflects every object vertically, matching lazer's ``OsuModHardRock`` ->
``ReflectVerticallyAlongPlayfield`` (``y -> 384 - y``, x untouched). A player on
HR arrives at the reflected position, so aim error must be measured against it.
"""
from __future__ import annotations

import slider

PLAYFIELD_HEIGHT = 384.0


def load_beatmap(map_path):
    return slider.Beatmap.from_path(map_path)


def mod_scale(r):
    """Map-time -> real-time multiplier (DT speeds up, HT slows down)."""
    if r.double_time:
        return 2.0 / 3.0
    if r.half_time:
        return 4.0 / 3.0
    return 1.0


def od_for(bm, r):
    """OD as judged, with the replay's Easy / Hard Rock applied."""
    return bm.od(easy=r.easy, hard_rock=r.hard_rock)


def cs_for(bm, r):
    """CS as judged, with the replay's Easy / Hard Rock applied."""
    return bm.cs(easy=r.easy, hard_rock=r.hard_rock)


def mod_string(r):
    """Compact mod label for reports (e.g. ``DT+HD``); ``NM`` when none."""
    names = [name for name, on in (("DT", r.double_time), ("HT", r.half_time),
                                   ("HD", r.hidden), ("HR", r.hard_rock),
                                   ("EZ", r.easy), ("FL", r.flashlight),
                                   ("NF", r.no_fail), ("RX", r.relax),
                                   ("AP", r.auto_pilot)) if on]
    return "+".join(names) if names else "NM"


def od_windows(od, scale):
    """Judgement half-windows in real ms for 300/100/50.

    ``scale`` carries DT/HT (the windows are defined in map time); OD itself must
    already be mod-adjusted -- slider's ``od(double_time=True)`` would scale the
    windows a second time.
    """
    w300 = (80 - 6 * od) * scale
    w100 = (140 - 8 * od) * scale
    w50 = (200 - 10 * od) * scale
    return w300, w100, w50


def build_objects(bm, scale, hard_rock=False):
    """list of dicts: {t, end, x, y, kind} with t/end in real ms.

    ``hard_rock`` reflects the playfield vertically (``obj.hard_rock`` does the
    transform in slider, so slider paths/positions stay consistent with the
    library's own judgement code).
    """
    objs = []
    for o in bm.hit_objects():
        oo = o.hard_rock if hard_rock else o
        kind = type(o).__name__
        t = oo.time.total_seconds() * 1000.0 * scale
        end = getattr(oo, "end_time", oo.time)
        end = end.total_seconds() * 1000.0 * scale
        pos = oo.position
        objs.append({"t": t, "end": end, "x": pos.x, "y": pos.y, "kind": kind})
    objs.sort(key=lambda d: d["t"])
    return objs


def circle_radius(cs):
    """Circle radius in osu! pixels for a given circle size."""
    return slider.beatmap.circle_radius(cs)
