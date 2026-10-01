"""Per-object structure fields: rhythm snap, geometry and difficulty.

This is the frozen per-object record schema (see ``docs/object_schema.md``).
Nothing here interprets the play: it computes the numbers Tier 1 will bucket
(rhythm snap, spacing, flow angle, osu!'s own per-object strains) so that every
later question -- "which structures do I fail?" -- is asked of the same row.

Fields added to each result row (see ``docs/object_schema.md`` for the units):

    spacing_r      distance to the previous object, in circle radii
    pattern        spacing-only bucket (dense/stream/jump/bigjump) -- legacy
    snap           gap to the previous object in quarter-beats (1.0 = 1/4,
                   2.0 = 1/2, 4.0 = 1/1); None without an uninherited point
    bpm            BPM at this object, as written in the .osu
    bpm_eff        BPM as played (``bpm`` scaled by DT/HT)
    angle_deg      turn between the previous two movement vectors: 0 = straight
                   (flow), 180 = a full reversal (anti-flow)
    strain_aim     osu!'s aim strain for this object (mod-aware)
    strain_speed   osu!'s speed strain for this object (mod-aware)
"""
from __future__ import annotations

import bisect
import math

SCHEMA_VERSION = 1

# the record fields written to out/<tag>_objects.json, in order
OBJECT_FIELDS = ("i", "t", "kind", "end_t", "x", "y", "result", "error_ms",
                 "aim_px", "aim_r", "key", "cursor_speed", "spacing_r",
                 "pattern", "snap", "bpm", "bpm_eff", "angle_deg", "strain_aim",
                 "strain_speed", "slider_tail_off", "slider_missed_ticks",
                 "slider_off_pct")


def beat_grid(bm):
    """(times_ms, beat_ms) for the map's uninherited timing points."""
    tps = sorted((p for p in bm.timing_points if (p.bpm or 0) > 0),
                 key=lambda p: p.offset)
    return ([p.offset.total_seconds() * 1000.0 for p in tps],
            [60000.0 / p.bpm for p in tps])


def _beat_ms_at(times, beats, t_ms):
    if not times:
        return None
    i = bisect.bisect_right(times, t_ms) - 1
    return beats[max(0, i)]


def _angle(a, b, c):
    """Turn in degrees between the movement into b and the movement into c."""
    v1 = (b["x"] - a["x"], b["y"] - a["y"])
    v2 = (c["x"] - b["x"], c["y"] - b["y"])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 <= 1e-6 or n2 <= 1e-6:
        return None
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def _strains(bm, mods):
    """Per-object (speed, aim) strains, or None when the library cannot say.

    ``bm.hit_object_difficulty`` returns one row per object *after* the first,
    so row ``i - 1`` belongs to object ``i``.
    """
    try:
        _times, strains = bm.hit_object_difficulty(**mods)
    except Exception:          # exotic maps / library limits: degrade, don't fail
        return None
    return strains


def annotate(results, bm, radius, scale, strain_mods=None, bpm_scale=None):
    """Add the structure fields to every result row (in place).

    ``scale`` is the calibrated time scale of the rows; ``bpm_scale`` is the
    scale implied by the replay's mods, which is what the *player* felt -- they
    differ when the calibration overrides a misleading mod flag.
    """
    times, beats = beat_grid(bm)
    strains = _strains(bm, strain_mods or {})
    for i, x in enumerate(results):
        x["snap"] = None
        x["bpm"] = None
        x["bpm_eff"] = None
        x["angle_deg"] = None
        x["strain_aim"] = None
        x["strain_speed"] = None
        if i > 0:
            dt = x["t"] - results[i - 1]["t"]
            beat_ms = _beat_ms_at(times, beats, x["t"] / scale)
            if beat_ms and dt > 0:
                x["bpm"] = 60000.0 / beat_ms              # as written in the .osu
                x["bpm_eff"] = 60000.0 / (beat_ms * (bpm_scale or scale))  # as played
                x["snap"] = dt / (beat_ms * scale / 4.0)
        if i > 1:
            x["angle_deg"] = _angle(results[i - 2], results[i - 1], x)
        if strains is not None and 0 < i <= len(strains):
            x["strain_speed"] = float(strains[i - 1][0])
            x["strain_aim"] = float(strains[i - 1][1])
    return results


def _r(value, digits=3):
    return None if value is None else round(float(value), digits)


def object_records(results, radius):
    """The per-object records written beside the metrics JSON (frozen schema)."""
    records = []
    for i, x in enumerate(results):
        aim = x.get("aim")
        records.append({
            "i": i,
            "t": _r(x["t"], 1),
            "kind": x["kind"],
            "end_t": _r(x.get("end"), 1),
            "x": _r(x["x"], 1),
            "y": _r(x["y"], 1),
            "result": x["result"],
            "error_ms": _r(x.get("error"), 2),
            "aim_px": _r(aim, 2),
            "aim_r": _r(aim / radius, 3) if aim is not None else None,
            "key": x.get("key"),
            "cursor_speed": _r(x.get("cursor_speed")),
            "spacing_r": _r(x.get("spacing_r")),
            "pattern": x.get("pattern"),
            "snap": _r(x.get("snap")),
            "bpm": _r(x.get("bpm"), 2),
            "bpm_eff": _r(x.get("bpm_eff"), 2),
            "angle_deg": _r(x.get("angle_deg"), 1),
            "strain_aim": _r(x.get("strain_aim"), 2),
            "strain_speed": _r(x.get("strain_speed"), 2),
            "slider_tail_off": x.get("slider_tail_off"),
            "slider_missed_ticks": x.get("slider_missed_ticks"),
            "slider_off_pct": _r(x.get("slider_off_pct"), 1),
        })
    return records
