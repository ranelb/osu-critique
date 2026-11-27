"""Geometric pattern segments: lines, polygons, arcs, zigzags, stacks.

``patterns.bucket`` labels one object by its spacing alone. This module labels
*runs of objects* by the shape their path draws, which is what a player means by
"a triangle" or "a back-and-forth".

Three detectors, because mapped shapes come in three kinds:

- **cycles** -- the positions repeat with period ``p`` (a, b, c, a, b, c, ...).
  That is a stack (p=1), a back-and-forth (p=2), a triangle (p=3), a
  square/rectangle/quad (p=4), a pentagon, hexagon or star (p=5, 6). A cycle has
  to come round twice, because any three notes "form a triangle".
- **fits** -- every note within a tolerance of a straight line (a line) or of one
  circle (an arc, or a circle once the sweep reaches ~300 degrees). Corner
  angles are too noisy for hand-placed notes, so positions are fitted instead.
- **turn rule** -- alternating corners of similar size and equal legs are a zigzag.
  A back-and-forth is deliberately *only* the p=2 cycle: notes that return to the
  same two spots. Looser "sharp turns" rules mostly found chance structure.

Everything is geometry in circle radii, never pixels, and nothing here looks at
the player: it is a property of the map. Legs shorter than ``MIN_LEG_R`` have no
meaningful direction (``docs/ROADMAP.md``), so they end a line, arc or zigzag;
objects that sit on top of each other are a stack instead.

The result is a list of non-overlapping segments, left to right, longest
candidate first at each position. Objects no rule explains stay unlabelled --
``summarize`` reports that share, and it is meant to be large on loosely mapped
maps rather than forced into a label.

Turn sign: osu! coordinates have y pointing down, so a positive turn is
clockwise *as drawn on the playfield*.

Known gaps: polygons that drift or rotate (no exact repeat), sliders as nodes of
a shape (a slider counts by its head position), radial bursts through a centre
(they come out unlabelled), and anything that is not one of the shapes above.
"""
from __future__ import annotations

import math
import statistics as st

import numpy as np

# --- thresholds: one table, each with the reason it is what it is ----------

#: a leg shorter than this many radii has no direction (see ROADMAP)
MIN_LEG_R = 1.5
#: objects closer than this are on top of each other -> stack
STACK_R = 1.0
#: line and arc/circle are *fits*: every note must lie within this many radii of the
#: fitted line or circle. Corner angles are far too noisy for hand-placed notes (a
#: 0.3-radius slip on a 3-radius leg is already ~10 degrees of turn).
FIT_TOL_R = 0.6
#: zigzag: corner size range, and how far a corner may differ from the last
ZIG_MIN, ZIG_MAX, ZIG_DELTA, ZIG_RATIO = 30.0, 150.0, 30.0, 1.5
#: arc/circle: central angle per note, and the total sweep that makes it a circle
ARC_MIN, ARC_MAX = 8.0, 55.0
CIRCLE_SWEEP = 300.0
#: consecutive legs of one shape differ in length by at most this factor
LEG_RATIO = 1.8
#: a cycle repeats a position within this many radii; its points are this far apart
CYCLE_TOL_R = 1.0
CYCLE_SEP_R = 1.5
CYCLE_MAX_P = 6
#: polygon corner tests: a square's corners are 90 +- this, its sides within this ratio
RIGHT_ANGLE_TOL = 30.0
SQUARE_RATIO = 1.5
#: a regular p-gon turns 360/p per corner, a p-pointed star a multiple of that
STAR_RATIO = 1.5
#: a triangle's third point must stand at least this many radii off the line of the others
TRIANGLE_HEIGHT_R = 1.5

#: read sliders' exits as shape nodes as well as their heads (PLAN phase C). Decided
#: by the labelled-set score; see docs/geometry.md for the numbers.
SLIDER_TAILS_DEFAULT = False

#: objects a shape needs before it is a segment
MIN_OBJECTS = {"line": 5, "zigzag": 6, "arc": 5, "circle": 5, "stack": 4}
#: tie-break when two shapes cover the same number of objects (lower wins)
PRIORITY = {"triangle": 0, "square": 0, "rectangle": 0, "quad": 0,
            "pentagon": 0, "hexagon": 0, "star": 0, "polygon": 0,
            "back_and_forth": 1, "zigzag": 2, "circle": 3, "arc": 3,
            "line": 4, "stack": 5}

SHAPES = tuple(sorted(PRIORITY, key=lambda s: (PRIORITY[s], s)))


# ------------------------------------------------------------------ helpers --

def _wrap(deg):
    """Wrap an angle difference to (-180, 180]."""
    deg = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if deg == -180.0 else deg


def _similar(a, b):
    lo, hi = min(a, b), max(a, b)
    return lo > 0 and hi / lo <= LEG_RATIO


def _end(o):
    return o.get("end_x", o["x"]), o.get("end_y", o["y"])


class _Path:
    """Legs and corners of an object list, in radii and degrees.

    ``nodes`` picks what a shape is drawn through:

    - ``"mixed"`` (default, the historical behaviour): nodes are object heads, but
      leg i runs from the previous object's *exit* to head i;
    - ``"head"``: nodes and legs are head to head;
    - ``"exit"``: nodes and legs are exit to exit (a slider is its tail).

    The last two only differ from each other on sliders (``slider_tails``).
    """

    def __init__(self, objs, radius, nodes="mixed"):
        self.objs = objs
        self.n = len(objs)
        self.r = float(radius)
        self.nodes = nodes
        n = self.n
        self.leg_r = [None] * n        # leg i: previous node -> node i (see ``nodes``)
        self.ang = [None] * n          # its heading, degrees, None when too short
        for i in range(1, n):
            if nodes == "head":
                ex, ey = objs[i - 1]["x"], objs[i - 1]["y"]
            else:
                ex, ey = _end(objs[i - 1])
            hx, hy = self.pos(i)
            dx, dy = hx - ex, hy - ey
            length = math.hypot(dx, dy) / self.r
            self.leg_r[i] = length
            if length >= MIN_LEG_R:
                self.ang[i] = math.degrees(math.atan2(dy, dx))
        # turn at node i = from leg i into leg i+1 (None when either has no heading)
        self.turn = [None] * n
        for i in range(1, n - 1):
            if self.ang[i] is not None and self.ang[i + 1] is not None:
                self.turn[i] = _wrap(self.ang[i + 1] - self.ang[i])

    def pos(self, i):
        if self.nodes == "exit":
            return _end(self.objs[i])
        return self.objs[i]["x"], self.objs[i]["y"]

    def dist_r(self, i, j):
        (ax, ay), (bx, by) = self.pos(i), self.pos(j)
        return math.hypot(ax - bx, ay - by) / self.r


# ---------------------------------------------------------------- detectors --
# Each takes (path, s) and returns None or (shape, e, extra) with objects
# s..e inclusive. They extend as far as the rule keeps holding.

def _line_fits(P, s, e):
    """Notes s..e on one straight run, moving forward the whole way."""
    (ax, ay), (bx, by) = P.pos(s), P.pos(e)
    length = math.hypot(bx - ax, by - ay)
    if length < (e - s) * MIN_LEG_R * P.r * 0.8:
        return False
    ux, uy = (bx - ax) / length, (by - ay) / length
    prev = P.pos(s)
    for i in range(s, e + 1):
        x, y = P.pos(i)
        if abs((x - ax) * uy - (y - ay) * ux) > FIT_TOL_R * P.r:
            return False
        if i > s and (x - prev[0]) * ux + (y - prev[1]) * uy < 0.75 * P.r:
            return False
        prev = (x, y)
    return True


def _line(P, s):
    best = None
    for e in range(s + 1, P.n):
        if P.leg_r[e] < MIN_LEG_R:
            break
        if e - s + 1 >= MIN_OBJECTS["line"]:
            if not _line_fits(P, s, e):
                break
            best = e
    return ("line", best, {}) if best is not None else None


def _zigzag(P, s):
    e, prev = s + 1, None
    while e + 1 < P.n:
        t = P.turn[e]
        if t is None or not ZIG_MIN <= abs(t) <= ZIG_MAX:
            break
        if prev is not None:
            if t * prev >= 0 or abs(abs(t) - abs(prev)) > ZIG_DELTA:
                break
        if max(P.leg_r[e], P.leg_r[e + 1]) > ZIG_RATIO * min(P.leg_r[e], P.leg_r[e + 1]):
            break
        prev, e = t, e + 1
    return ("zigzag", e, {}) if e - s + 1 >= MIN_OBJECTS["zigzag"] else None


def _arc_fit(P, s, e):
    """Sweep in degrees of the circle through notes s..e, or None if they are not on one."""
    pts = np.array([P.pos(i) for i in range(s, e + 1)], dtype=float)
    # least-squares circle (Kasa): fitting all notes, not three of them, so one
    # noisy note does not drag the whole fit off
    design = np.column_stack([2 * pts[:, 0], 2 * pts[:, 1], np.ones(len(pts))])
    target = (pts ** 2).sum(axis=1)
    try:
        (cx, cy, c), *_ = np.linalg.lstsq(design, target, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if c + cx * cx + cy * cy <= 0:
        return None
    radius = math.sqrt(c + cx * cx + cy * cy)
    if radius < MIN_LEG_R * P.r * 0.5 or radius > 40 * P.r:
        return None
    # notes closer than MIN_LEG_R have no direction, and a run a straight line
    # explains is a line: an arc has to bend by more than the fit tolerance
    if any(P.leg_r[i] < MIN_LEG_R for i in range(s + 1, e + 1)) or _line_fits(P, s, e):
        return None
    angles, total = [], 0.0
    for i in range(s, e + 1):
        x, y = P.pos(i)
        if abs(math.hypot(x - cx, y - cy) - radius) > FIT_TOL_R * P.r:
            return None
        angles.append(math.degrees(math.atan2(y - cy, x - cx)))
    steps = [_wrap(angles[k + 1] - angles[k]) for k in range(len(angles) - 1)]
    sign = 1.0 if sum(steps) > 0 else -1.0
    if any(t * sign <= 0 or not ARC_MIN <= abs(t) <= ARC_MAX for t in steps):
        return None
    if any(not _similar(P.leg_r[i], P.leg_r[i + 1]) for i in range(s + 1, e)):
        return None
    return sum(steps)


def _arc(P, s):
    best = None
    for e in range(s + MIN_OBJECTS["arc"] - 1, P.n):
        sweep = _arc_fit(P, s, e)
        if sweep is None:
            break
        best = (e, sweep)
    if best is None:
        return None
    e, sweep = best
    return ("circle" if abs(sweep) >= CIRCLE_SWEEP else "arc"), e, {"sweep": sweep}


def _polygon_name(P, pts):
    """Name the p vertices ``pts`` (in visit order) and their winding, or None."""
    p = len(pts)
    sides = [math.hypot(pts[(k + 1) % p][0] - pts[k][0],
                        pts[(k + 1) % p][1] - pts[k][1]) / P.r for k in range(p)]
    if min(sides) < CYCLE_SEP_R:
        return None
    turns = []
    for k in range(p):
        a, b, c = pts[k - 1], pts[k], pts[(k + 1) % p]
        h1 = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        h2 = math.degrees(math.atan2(c[1] - b[1], c[0] - b[0]))
        turns.append(_wrap(h2 - h1))
    convex = all(t > 0 for t in turns) or all(t < 0 for t in turns)
    winding = "cw" if sum(turns) > 0 else "ccw"
    if p == 2:
        return "back_and_forth", None
    if p == 3:
        a, b, c = pts
        base = math.hypot(c[0] - a[0], c[1] - a[1]) or 1e-9
        height = abs((c[0] - a[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (c[1] - a[1])) / base
        if height / P.r < TRIANGLE_HEIGHT_R:
            return None
        return "triangle", winding
    if p == 4:
        if not convex:
            return "quad", None
        right = all(abs(abs(t) - 90.0) <= RIGHT_ANGLE_TOL for t in turns)
        if right:
            even = max(sides) / min(sides) <= SQUARE_RATIO
            return ("square" if even else "rectangle"), winding
        return "quad", winding
    if not convex:
        return "polygon", None
    mean_turn = st.mean(abs(t) for t in turns)
    if mean_turn > STAR_RATIO * 360.0 / p:        # skips vertices: a star, not a p-gon
        return "star", winding
    return ("pentagon" if p == 5 else "hexagon"), winding


def _cycle(P, s):
    """Smallest period p whose positions repeat at least twice from ``s``."""
    for p in range(1, CYCLE_MAX_P + 1):
        e = s + p - 1
        while e + 1 < P.n and P.dist_r(e + 1, e + 1 - p) <= CYCLE_TOL_R:
            e += 1
        # the cycle has to come round twice: a b c a b c, not a b c a b (any three
        # notes form a triangle, and a lap and a half is mostly chance)
        if e - s + 1 < max(2 * p, MIN_OBJECTS["stack"]):
            continue
        resid = st.mean(P.dist_r(i, i - p) for i in range(s + p, e + 1))
        if p == 1:
            if max(P.dist_r(i, s) for i in range(s, e + 1)) <= STACK_R:
                return "stack", e, {"period": 1, "residual_r": resid}
            continue
        # each vertex is the mean of every visit to it: hand-placed noise shrinks
        # with the number of laps
        verts = []
        for k in range(p):
            visits = [P.pos(i) for i in range(s + k, e + 1, p)]
            verts.append((st.mean(v[0] for v in visits), st.mean(v[1] for v in visits)))
        named = _polygon_name(P, verts)
        if named is None:
            continue
        shape, winding = named
        return shape, e, {"period": p, "residual_r": resid, "dir": winding}
    return None


_DETECTORS = (_cycle, _zigzag, _arc, _line)


# -------------------------------------------------------------------- build --

def _segment(P, s, e, shape, extra, beat_ms, tag_nodes=False):
    objs = P.objs
    gaps = [objs[i]["t"] - objs[i - 1]["t"] for i in range(s + 1, e + 1)]
    legs = [P.leg_r[i] for i in range(s + 1, e + 1)]
    turns = [P.turn[i] for i in range(s + 1, e) if P.turn[i] is not None]
    seg = {
        "shape": shape, "start": s, "end": e, "n": e - s + 1,
        "t0": objs[s]["t"], "t1": objs[e]["t"],
        "rate_ms": st.median(gaps) if gaps else None,
        "spacing_r": st.median(legs) if legs else None,
        "has_sliders": any(o.get("kind") == "Slider" for o in objs[s:e + 1]),
        "period": extra.get("period"),
        "dir": extra.get("dir"),
        "residual_r": extra.get("residual_r"),
        "turn_sd": st.pstdev(turns) if len(turns) > 1 else None,
    }
    if tag_nodes:
        seg["nodes"] = P.nodes
    if "sweep" in extra:
        seg["sweep"] = extra["sweep"]
        seg["dir"] = "cw" if extra["sweep"] > 0 else "ccw"
    seg["beats"] = (seg["rate_ms"] / beat_ms
                    if beat_ms and seg["rate_ms"] else None)
    return seg


#: how many starts ahead to look for a candidate that reaches further than the one
#: found here (junk right before a shape can look like its first notes)
LOOKAHEAD = 3


def _best(Ps, i):
    """The longest candidate starting at object ``i`` (ties: higher priority, then the
    earlier path in ``Ps``). Returns ``(key, shape, e, extra, P)``."""
    best = None
    for P in Ps:
        for detect in _DETECTORS:
            found = detect(P, i)
            if found is None:
                continue
            shape, e, extra = found
            key = (e - i, -PRIORITY[shape])
            if best is None or key > best[0]:
                best = (key, shape, e, extra, P)
    return best


def classify(objs, radius, beat_ms=None, slider_tails=SLIDER_TAILS_DEFAULT):
    """Segments of ``objs`` (build_objects rows), left to right, non-overlapping.

    ``radius`` is the circle radius in osu! pixels; ``beat_ms`` (optional) adds a
    ``beats`` field (note gap in beats) so a consumer can say "1/4" honestly.

    ``slider_tails`` (see ``SLIDER_TAILS_DEFAULT``) also reads the map through
    sliders' exits: a shape may be drawn through heads (head-to-head legs) or through
    tails (exit-to-exit legs), as well as the historical mixed legs (which zigzags
    on real maps still need), and the longer candidate wins, mixed first on ties. A map with no sliders
    is classified exactly as with the flag off; segments carry ``nodes`` when it is on.
    """
    if slider_tails and any(o.get("kind") == "Slider" for o in objs):
        P = [_Path(objs, radius), _Path(objs, radius, "head"), _Path(objs, radius, "exit")]
        tag = True
    else:
        P, tag = [_Path(objs, radius)], False
    n_objs = len(objs)
    segs, i = [], 0
    while i < n_objs:
        best = _best(P, i)
        if best is None:
            i += 1
            continue
        moved = True
        while moved:
            moved = False
            for j in range(i + 1, min(i + LOOKAHEAD, best[2]) + 1):
                alt = _best(P, j)
                if alt is not None and alt[2] > best[2] and alt[2] - j > best[2] - i:
                    best, i, moved = alt, j, True
                    break
        _key, shape, e, extra, Pw = best
        segs.append(_segment(Pw, i, e, shape, extra, beat_ms, tag))
        i = e + 1
    return segs


def label_objects(objs, segs):
    """Write ``shape`` / ``shape_id`` onto each object (None outside a segment)."""
    for o in objs:
        o["shape"], o["shape_id"] = None, None
    for k, seg in enumerate(segs):
        for i in range(seg["start"], seg["end"] + 1):
            objs[i]["shape"], objs[i]["shape_id"] = seg["shape"], k
    return objs


def summarize(segs, n_objects):
    """Counts and shares per shape, plus how much of the map no rule explains."""
    by = {}
    for seg in segs:
        row = by.setdefault(seg["shape"], {"segments": 0, "objects": 0})
        row["segments"] += 1
        row["objects"] += seg["n"]
    covered = sum(r["objects"] for r in by.values())
    for row in by.values():
        row["share"] = row["objects"] / n_objects if n_objects else 0.0
    return {"n_objects": n_objects, "covered": covered,
            "coverage": covered / n_objects if n_objects else 0.0,
            "shapes": by}
