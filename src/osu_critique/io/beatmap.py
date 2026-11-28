"""Beatmap (.osu) loading, object building and mod/time scaling.

Mods that change geometry or judgement are applied here rather than ignored:
the hit windows come from the mod-adjusted OD (``od_for``/``cs_for``) and Hard
Rock reflects every object vertically, matching lazer's ``OsuModHardRock`` ->
``ReflectVerticallyAlongPlayfield`` (``y -> 384 - y``, x untouched). A player on
HR arrives at the reflected position, so aim error must be measured against it.
"""
from __future__ import annotations

import bisect
import math

import numpy as np
import slider
from slider.position import Position

PLAYFIELD_HEIGHT = 384.0


def _catmull_call(self, t):
    """``slider.curve.Catmull.__call__`` with the scalar conversion NumPy 2.5 accepts.

    slider 0.8.4 does ``float(S @ h @ C)`` on a 1x1 array. NumPy deprecated that
    in 1.25 and made it a TypeError ("only 0-dimensional arrays can be converted
    to Python scalars") in 2.5, so every map with a Catmull slider failed to
    parse. Same maths as the library, ``.item()`` instead of ``float()``.
    """
    if len(self.points) == 1:
        return self.points[0]
    S = np.array([t**3, t**2, t, 1])
    curve_index = math.ceil(t * len(self.Cxs)) - 1
    Cx = self.Cxs[curve_index]
    Cy = self.Cys[curve_index]
    px = (S @ self.h) @ Cx
    py = (S @ self.h) @ Cy
    return Position(float(np.asarray(px).item()), float(np.asarray(py).item()))


def _patch_slider() -> None:
    """Install :func:`_catmull_call` when the library's own breaks (idempotent)."""
    import slider.curve as sc
    try:
        float(np.ones((1, 1)))
        return                                   # old NumPy: the library works
    except TypeError:
        pass
    sc.Catmull.__call__ = _catmull_call


_patch_slider()


def load_beatmap(map_path):
    return slider.Beatmap.from_path(map_path)


def mod_scale(r, score_meta=None):
    """Map-time -> real-time multiplier (DT speeds up, HT slows down).

    A lazer export can carry a *custom* rate in its trailing score-info block
    (e.g. DT at 1.2x). The legacy mod bitmask only says "DT", so when
    ``score_meta`` is available its ``speed_change`` wins: ``1 / rate`` is the
    real time multiplier. Falls back to the flag for stable-era replays.
    """
    speed = (score_meta or {}).get("speed_change")
    if speed and speed > 0:
        return 1.0 / float(speed)
    if r.double_time:
        return 2.0 / 3.0
    if r.half_time:
        return 4.0 / 3.0
    return 1.0


def rate_label(r, score_meta=None):
    """Human label for the rate the score block (or the flags) implies."""
    speed = (score_meta or {}).get("speed_change")
    if speed and speed > 0 and abs(speed - 1.0) > 1e-9:
        name = "DT" if speed > 1.0 else "HT"
        return f"{name} at {speed:.2f}x"
    if r.double_time:
        return "DT"
    if r.half_time:
        return "HT"
    return None


def timing_context(bm):
    """Sorted timing points and their offsets (ms), for per-object SV/kiai."""
    points = sorted(getattr(bm, "timing_points", []) or [],
                    key=lambda p: p.offset)
    return points, [p.offset.total_seconds() * 1000.0 for p in points]


def sv_kiai_at(points, offsets, t_ms):
    """(SV multiplier, kiai) at map time ``t_ms``.

    osu! stores inherited (green) points with a negative ``ms_per_beat``; their
    SV multiplier is ``-100 / ms_per_beat``. An uninherited point resets SV to
    1.0. Kiai is inherited from the latest point of either kind.
    """
    if not points:
        return 1.0, False
    i = max(0, bisect.bisect_right(offsets, t_ms) - 1)
    point = points[i]
    sv = 1.0
    ms_per_beat = getattr(point, "ms_per_beat", None)
    if ms_per_beat is not None and ms_per_beat < 0:
        sv = -100.0 / ms_per_beat
    return (float(sv) if sv > 0 else 1.0), bool(getattr(point, "kiai_mode", False))


def slider_tail(oo):
    """Cursor position at the slider's final tail (repeats fold back)."""
    spans = max(1, int(getattr(oo, "repeat", 1) or 1))
    at = 0.0 if spans % 2 == 0 else 1.0
    try:
        pos = oo.curve(at)
        return float(pos.x), float(pos.y)
    except Exception:                      # exotic curve: fall back to the head
        pos = oo.position
        return float(pos.x), float(pos.y)


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
    """list of dicts: geometry, slider tails and per-object timing context.

    ``t``/``end`` are real ms. ``end_x``/``end_y`` are where the cursor must be
    when the object ends (a slider's tail, repeats folded back); spacing and the
    required cursor speed use that, not the slider head. ``sv`` and ``kiai`` are
    the map's own scroll-velocity multiplier and kiai flag at the object;
    ``curve_type``/``slider_path_px``/``repeats`` describe a slider's body.

    ``hard_rock`` reflects the playfield vertically (``obj.hard_rock`` does the
    transform in slider, so slider paths/positions stay consistent with the
    library's own judgement code).
    """
    points, offsets = timing_context(bm)
    objs = []
    for o in bm.hit_objects():
        oo = o.hard_rock if hard_rock else o
        kind = type(o).__name__
        map_ms = oo.time.total_seconds() * 1000.0
        t = map_ms * scale
        end = getattr(oo, "end_time", oo.time)
        end = end.total_seconds() * 1000.0 * scale
        pos = oo.position
        sv, kiai = sv_kiai_at(points, offsets, map_ms)
        is_slider = kind == "Slider"
        if is_slider:
            end_x, end_y = slider_tail(oo)
        else:
            end_x, end_y = float(pos.x), float(pos.y)
        objs.append({
            "t": t, "end": end, "x": pos.x, "y": pos.y, "kind": kind,
            "end_x": end_x, "end_y": end_y,
            "sv": sv, "kiai": kiai,
            "curve_type": (type(getattr(oo, "curve", None)).__name__
                           if is_slider else None),
            "slider_path_px": ((float(getattr(oo, "pixel_length", None)
                                       or getattr(oo, "length", None) or 0.0))
                               if is_slider else None),
            "repeats": (max(1, int(getattr(oo, "repeat", 1) or 1))
                        if is_slider else None),
        })
    objs.sort(key=lambda d: d["t"])
    return objs


def circle_radius(cs):
    """Circle radius in osu! pixels for a given circle size."""
    return slider.beatmap.circle_radius(cs)
