"""Per-run visual boards, computed server-side from the artifacts.

Two questions the numbers do not answer on their own:

* **which misses were near-misses** — the ones where the cursor got close and
  the press still landed outside, ranked by closest approach (a small `closest_r`
  is "you almost had it", not "you never looked");
* **which stretches were unusually good** — clean, fast stream segments, which
  are the ones worth trusting as a model for the rest.

Everything here is derived from the metrics document and the per-object record;
no frames, no matplotlib. The web layer draws it on a canvas.
"""
from __future__ import annotations

PLAYFIELD = (512.0, 384.0)


def _objects_by_index(objects):
    return {o.get("i"): o for o in objects if isinstance(o.get("i"), int)}


def _num(value, digits=2):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _clip(value, low, high):
    return max(low, min(high, value))


def miss_boards(metrics, objects, limit: int = 8) -> list[dict]:
    """The near-misses, each with its 5-note window for a small board."""
    rows = ((metrics.get("autopsy") or {}).get("misses") or {}).get("rows") or []
    by_i = _objects_by_index(objects)
    printable = [m for m in rows if m.get("i") in by_i]
    # closest approach first: those are the misses that were almost hits
    printable.sort(key=lambda m: (m.get("closest_r") is None, m.get("closest_r") or 9))
    boards = []
    for miss in printable[:limit]:
        i = miss["i"]
        chain = [by_i[k] for k in range(i - 2, i + 3) if k in by_i]
        boards.append({
            "i": i,
            "t": _num(miss.get("t"), 0),
            "kind": miss.get("kind"),
            "closest_r": _num(miss.get("closest_r")),
            "aim_at_press_r": _num(miss.get("aim_at_press_r")),
            "gap_r": _num(miss.get("gap_r")),
            "turn_deg": _num(miss.get("turn_deg"), 0),
            "press_ms": _num(miss.get("press_ms"), 0),
            "chain": [{"i": c["i"], "x": _clip(c.get("x", 0), 0, PLAYFIELD[0]),
                       "y": _clip(c.get("y", 0), 0, PLAYFIELD[1]),
                       "kind": c.get("kind"), "result": c.get("result")}
                      for c in chain],
        })
    return boards


def miss_heat(metrics, objects) -> list[dict]:
    """Every miss as a point on the playfield (for one overview canvas)."""
    by_i = _objects_by_index(objects)
    rows = ((metrics.get("autopsy") or {}).get("misses") or {}).get("rows") or []
    out = []
    for miss in rows:
        obj = by_i.get(miss.get("i"))
        if obj is None:
            continue
        out.append({"x": _clip(obj.get("x", 0), 0, PLAYFIELD[0]),
                    "y": _clip(obj.get("y", 0), 0, PLAYFIELD[1]),
                    "closest_r": _num(miss.get("closest_r"))})
    return out


def good_stretches(metrics, limit: int = 3) -> list[dict]:
    """Clean stretches at speed: stream segments first, quarters as the fallback.

    A short map may have no stream segment longer than four notes, so the
    quarter split (already in the metrics) is what a run like that can offer.
    """
    segments = ((metrics.get("streams") or {}).get("segments")) or []
    clean = [s for s in segments
             if (s.get("miss") or 0) == 0 and (s.get("n") or 0) >= 8
             and (s.get("notes_per_s") or 0) >= 5]
    clean.sort(key=lambda s: ((s.get("notes_per_s") or 0) * (s.get("n") or 0)),
               reverse=True)
    if clean:
        return [{
            "kind": "stream",
            "t_start": _num(s.get("t_start"), 0),
            "t_end": _num(s.get("t_end"), 0),
            "n": s.get("n"),
            "notes_per_s": _num(s.get("notes_per_s"), 1),
            "gap_ms": _num(s.get("gap_ms"), 0),
            "alt_ratio": _num(s.get("alt_ratio"), 2),
        } for s in clean[:limit]]

    quarters = [q for q in (metrics.get("quarters") or [])
                if (q.get("miss") or 0) == 0 and (q.get("n") or 0) >= 40]
    quarters.sort(key=lambda q: q.get("std_err") or 1e9)
    out = []
    for q in quarters[:limit]:
        span = q.get("range") or [0, 0]
        out.append({
            "kind": "quarter",
            "t_start": _num(span[0], 0),
            "t_end": _num(span[1], 0),
            "n": q.get("n"),
            "notes_per_s": None,
            "gap_ms": None,
            "alt_ratio": None,
            "mean_err": _num(q.get("mean_err"), 1),
            "std_err": _num(q.get("std_err"), 1),
        })
    return out


def build(metrics, objects) -> dict:
    return {
        "playfield": {"w": PLAYFIELD[0], "h": PLAYFIELD[1]},
        "radius": _num(metrics.get("spacing_radius"), 2) or 40.0,
        "misses": miss_boards(metrics, objects),
        "heat": miss_heat(metrics, objects),
        "good": good_stretches(metrics),
    }
