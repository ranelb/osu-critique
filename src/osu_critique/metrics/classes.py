"""Per-object pattern classes: one place that names what each object *is*.

The map-side detectors each answer a different question about a run of objects:

    geometry   a repeated figure (triangle, square, circle, line, ...), unlabelled is normal
    walks      one lap of a polygon or star by equal legs and equal turns
    curves     a curvy stream / arc / circle fit on dense legs
    legs       distance x flow x tempo of the leg that arrives at the object (covers all)

``label(objs, radius, beat_at)`` runs them and writes six fields onto every object, in
place; ``class_keys`` turns those fields back into the set of class names the replay-side
miss-rate block and the recommender group by. Nothing here reads a replay, so it is a
property of the map *as played* (mod-adjusted radius and clock).

Fields (None / "none" = no class of that kind covers the object):

    shape      geometry shape of the segment the object is in
    walk       polygon/star walk shape
    curve      curve-fit shape (``curvy_stream``, ``arc``, ...)
    leg_dist   touching / close / medium / wide (None for the first object and spinners)
    leg_flow   none / flow / angle / snap
    leg_tempo  fast / mid / slow
"""
from __future__ import annotations

from . import curves, geometry, legs, rhythm, walks

FIELDS = ("shape", "walk", "curve", "leg_dist", "leg_flow", "leg_tempo")


def _paint(objs, key, segs):
    for s in segs:
        for i in range(s["start"], s["end"] + 1):
            if objs[i].get(key) is None:     # first segment wins where two touch
                objs[i][key] = s["shape"]


def label(objs, radius, beat_at=None, beat_ms=None):
    """Write the :data:`FIELDS` onto each object (``build_objects`` / result rows).

    ``objs`` need ``spacing_r`` (``patterns.add_pattern_labels``) for the geometry
    tempo tagging; ``beat_at(t)`` is the local beat length in the objects' own clock.
    """
    for o in objs:
        for f in FIELDS:
            o[f] = None
    segs = geometry.classify(objs, radius, beat_ms)
    rhythm.tag(objs, segs)
    geometry.label_objects(objs, segs)
    _paint(objs, "walk", walks.find(objs, radius, beat_at))
    _paint(objs, "curve", curves.find(objs, radius, beat_at))
    for o, lg in zip(objs, legs.legs(objs, radius, beat_at)):
        if lg:
            o["leg_dist"], o["leg_flow"], o["leg_tempo"] = lg["dist"], lg["flow"], lg["tempo"]
    return objs


def class_keys(o):
    """The class names an object belongs to (a set; may be empty for the first object)."""
    keys = set()
    for kind in ("shape", "walk", "curve"):
        if o.get(kind):
            keys.add(f"{kind}:{o[kind]}")
    if o.get("leg_dist"):
        keys.add(f"dist:{o['leg_dist']}")
        keys.add(f"leg:{o['leg_dist']}/{o['leg_flow']}")
    return keys


def stratum(o):
    """Difficulty-matching cell: leg distance x tempo (the 'adj' control of replay_join)."""
    return f"{o['leg_dist']}/{o['leg_tempo']}" if o.get("leg_dist") else None
