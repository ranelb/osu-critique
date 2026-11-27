"""Rhythm and tempo of geometry segments: what the notes *are* in time.

Geometry (``metrics/geometry.py``) says what shape a run of notes makes; it says
nothing about how fast they come. A circle of 24 notes 160 ms apart is a *spaced
stream* that happens to curve; the same circle at 400 ms is a slow flowing jump
pattern. This module adds that second axis without a second detector: runs come
from ``streams.find_runs`` (steady gap, any object kind, spinners break), and each
geometry segment is tagged by how much of it lies inside one.

    tag(objs, segs)  ->  segs, each gaining ``tempo``, ``run_share``, ``label``

``objs`` must be annotated (``structure.annotate``): ``spacing_r`` is read from
them. Classes are by the real gap in ms, never by a snap label, so a 1/4 stream at
100 BPM and a 1/2 stream at 200 BPM are the same speed and are called the same.
All numbers are in one table.
"""
from __future__ import annotations

from .streams import find_runs

STREAM_SHARE = 0.8        # a segment is "in a stream" when this much of it is in one run
STREAM_MAX_GAP = 160.0    # <= this gap (>= 375 BPM as 1/1; 1/4 at 94 BPM) is stream speed
BURST_MAX_GAP = 250.0     # find_runs' own ceiling: slower than this is not sustained
SPACED_R = 2.0            # median spacing from here up is "spaced" rather than "dense"
TOUCHING_R = 1.0          # median spacing under this is nearly stacked


def _runs_by_object(objs):
    """Map object index -> (run index, run gap_ms) for every object in a run."""
    pos = {id(o): i for i, o in enumerate(objs)}
    out = {}
    for ri, run in enumerate(find_runs(objs)):
        gaps = sorted(g for _x, _p, g, _v in run)
        gap = gaps[len(gaps) // 2]
        for x, _prev, _g, _v in run:
            out[pos[id(x)]] = (ri, gap)
    return out


def _tempo(in_run, gap_ms):
    if in_run and gap_ms is not None and gap_ms <= STREAM_MAX_GAP:
        return "stream"
    if in_run:
        return "burst"
    return "jumps"


def tag(objs, segs):
    """Add ``tempo`` (stream / burst / jumps), ``run_share`` and ``label`` to each segment."""
    by_obj = _runs_by_object(objs)
    for s in segs:
        idx = range(s["start"], s["end"] + 1)
        hit = [by_obj[i] for i in idx if i in by_obj]
        share = len(hit) / (s["end"] - s["start"] + 1)
        gap = None
        if hit:
            gaps = sorted(g for _ri, g in hit)
            gap = gaps[len(gaps) // 2]
        in_run = share >= STREAM_SHARE
        s["run_share"] = round(share, 3)
        s["tempo"] = _tempo(in_run, gap)
        s["label"] = describe(s)
    return segs


def describe(seg):
    """A short human name: 'spaced circle stream', 'dense line stream', 'triangle jumps'."""
    shape = seg["shape"].replace("_", " ")
    tempo = seg.get("tempo", "jumps")
    sp = seg.get("spacing_r") or 0.0
    if tempo == "jumps":
        return f"{shape} jumps"
    if sp < TOUCHING_R:
        weight = "dense"
    elif sp >= SPACED_R:
        weight = "spaced"
    else:
        weight = "tight"
    return f"{weight} {shape} {tempo}"
