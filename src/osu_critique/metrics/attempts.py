"""Cross-attempt structure: is a weakness stable, or one-off noise?

A single play says "these buckets were bad"; it cannot say whether they are a
*weakness*. The author has repeated plays of the same maps (RASPUTIN, Passcode,
overture), and the per-object schema carries ``beatmap_md5``, so the same map
across attempts is the strongest contrast the tool has (docs/ROADMAP.md item 4).

This layer groups the metrics files by beatmap, orders the attempts by play time,
drops duplicate exports of the same replay, and reports, per family and per shape
class:

- the rate in each attempt, the change from the first to the last, and whether
  that change is real (bigger than the two attempts' own sampling noise);
- which weaknesses are **stable** — worse than the play's overall rate in *every*
  attempt by at least ``STABLE_FACTOR`` — versus one-off;
- which are **volatile** — they swing across attempts, so practising them is a
  dart throw until the swing is explained.

Only the cheap version of the roadmap item: it reads the metrics files (families,
shapes, counts), not the per-object rows. A sqlite of per-object rows is not
needed until there are ~20-30 plays of one map.
"""
from __future__ import annotations

import collections

MIN_ATTEMPT_N = 10          # a rate is only compared from this many objects
STABLE_FACTOR = 1.5         # "clearly worse than the play" = this much worse
VOLATILE_PTS = 10.0         # points a rate must move to be called volatile
MIN_ATTEMPTS = 2
GATE_MIN, GATE_FRAC = 20, 0.03   # verdicts read only from buckets this solid


def solid_gate(n_objects):
    """The adaptive bucket gate the verdicts use (same shape as profile's target).

    A 150-object map is read from 10-object buckets; a 1000-object map is read
    from 20-object ones, where 3 % is the same idea (``profile.primary_target``
    scales its gate the same way).
    """
    return min(GATE_MIN, max(MIN_ATTEMPT_N, GATE_FRAC * (n_objects or 0)))


def key_of(metrics):
    """The replay identity used to drop duplicate exports of one play."""
    md5 = metrics.get("replay_md5")
    if md5 and md5.strip("0"):
        return ("replay", md5)
    return ("tag", metrics.get("beatmap_md5"), metrics.get("tag"),
            metrics.get("played_at"))


def group(rows):
    """``[(name, metrics)]`` -> ``{beatmap_md5: [metrics, ...]}`` in play order.

    Duplicate exports of the same play (same replay md5) collapse to one attempt;
    the extra names are recorded as ``duplicates`` so nothing is silently lost.
    """
    by_map = collections.defaultdict(list)
    for _name, m in rows:
        md5 = m.get("beatmap_md5")
        if not md5:
            continue
        by_map[md5].append(m)
    out = {}
    for md5, ms in by_map.items():
        seen = {}
        uniq = []
        for m in ms:
            k = key_of(m)
            if k in seen:
                seen[k].setdefault("duplicates", []).append(m.get("tag"))
                continue
            seen[k] = m
            uniq.append(m)
        uniq.sort(key=lambda m: (m.get("played_at") or "", m.get("tag") or ""))
        out[md5] = uniq
    return out


def _rate(m, family):
    for f in (m.get("profile") or {}).get("composition", []) or []:
        if f.get("family") == family:
            return f
    return None


def _shape_rate(m, cls):
    for c in (((m.get("autopsy") or {}).get("shapes") or {}).get("classes")
              or []):
        if c.get("class") == cls:
            return c
    return None


def _non300(m):
    """The play's own off-300 rate, from *our* judgement (falls back to accuracy)."""
    det = m.get("counts_detected")
    n = m.get("n_objects")
    if det and n:
        return (n - det.get("300", 0)) / n
    acc = m.get("accuracy")
    return None if acc is None else 1.0 - acc


def _compare_series(series, min_n, gate):
    """One row per name present in >=2 attempts, with a stability verdict."""
    out = []
    for name, entries in sorted(series.items()):
        known = [(m, e) for m, e in entries if e is not None]
        if len(known) < MIN_ATTEMPTS:
            continue
        rates = [e["non300_rate"] for _m, e in known
                 if e.get("non300_rate") is not None]
        ns = [e.get("n") or 0 for _m, e in known]
        if len(rates) < MIN_ATTEMPTS or min(ns) < min_n:
            out.append({"name": name, "n": ns, "rates": rates,
                        "reported": False, "solid": False})
            continue
        overall = [_non300(m) for m, _e in known]
        first, last = rates[0], rates[-1]
        # the verdict is only read from buckets that are populated everywhere:
        # a 10-object bucket on a 400-object map swings by chance
        solid = min(ns) >= gate
        worse_every = all(o is not None and r >= STABLE_FACTOR * o
                          for r, o in zip(rates, overall))
        row = {
            "name": name,
            "n": ns,
            "rates": rates,
            "delta_pts": (last - first) * 100.0,
            "min_pts": (min(rates) - max(rates)) * 100.0,
            "volatile": (max(rates) - min(rates)) * 100.0 >= VOLATILE_PTS,
            "stable_weakness": bool(worse_every and solid),
            "vs_overall": [round(r / o, 2) if o else None
                           for r, o in zip(rates, overall)],
            "reported": True,
            "solid": bool(solid),
        }
        out.append(row)
    return out


def _series(attempts, getter):
    """``name -> [(attempt, entry-or-None)]``, aligned to the attempt order."""
    s = collections.defaultdict(lambda: [None] * len(attempts))
    for i, m in enumerate(attempts):
        for f in getter(m) or []:
            name = f.get("family") or f.get("class")
            if s[name][i] is None:
                s[name][i] = f
    return {name: list(zip(attempts, entries)) for name, entries in s.items()}


def compare(attempts, min_n=None):
    """One map's attempts -> the comparison block (empty if only one attempt)."""
    min_n = MIN_ATTEMPT_N if min_n is None else min_n
    if len(attempts) < MIN_ATTEMPTS:
        return {"n_attempts": len(attempts),
                "attempts": [{"tag": m.get("tag"), "played_at": m.get("played_at"),
                              "accuracy": m.get("accuracy"),
                              "non300_rate": _non300(m),
                              "n_objects": m.get("n_objects"),
                              "trustworthy": (m.get("trust") or {}).get("trustworthy"),
                              "duplicates": m.get("duplicates", [])}
                             for m in attempts],
                "families": [], "shapes": [], "gate": solid_gate(
                    attempts[0].get("n_objects") if attempts else 0),
                "stable_weaknesses": [], "volatile": [], "verdict": None}
    gate = max(min_n, solid_gate(attempts[0].get("n_objects")))
    fams = _compare_series(_series(attempts, lambda m: (m.get("profile") or {})
                                   .get("composition")), min_n, gate)
    shapes = _compare_series(
        _series(attempts, lambda m: (((m.get("autopsy") or {}).get("shapes") or {})
                                     .get("classes"))), min_n, gate)
    series = fams + shapes
    stable = [f["name"] for f in series if f.get("stable_weakness")]
    volatile = [f["name"] for f in series
                if f.get("volatile") and f.get("solid")
                and f["name"] not in stable]
    return {
        "n_attempts": len(attempts),
        "gate": gate,
        "attempts": [{"tag": m.get("tag"), "played_at": m.get("played_at"),
                      "accuracy": m.get("accuracy"),
                      "non300_rate": _non300(m),
                      "n_objects": m.get("n_objects"),
                      "trustworthy": (m.get("trust") or {}).get("trustworthy"),
                      "duplicates": m.get("duplicates", [])}
                     for m in attempts],
        "families": fams,
        "shapes": shapes,
        "stable_weaknesses": stable,
        "volatile": volatile,
        "verdict": _verdict(stable, volatile, len(attempts)),
    }


def _verdict(stable, volatile, n_attempts):
    if not stable and not volatile:
        return (f"{n_attempts} attempts: nothing consistently worse than the play "
                "itself and nothing that swings — no structural weakness visible.")
    bits = []
    if stable:
        bits.append("consistent weakness (worse than the play in every attempt): "
                    + ", ".join(stable))
    if volatile:
        bits.append("swings between attempts (one-off or session noise until "
                    "explained, not a stable weakness): " + ", ".join(volatile))
    return f"{n_attempts} attempts — " + "; ".join(bits) + "."


def build(rows, min_n=None):
    """``[(name, metrics)]`` -> the whole cross-attempt block."""
    maps = []
    for md5, attempts in group(rows).items():
        maps.append({"beatmap_md5": md5,
                     "map": attempts[0].get("map"),
                     "player": attempts[0].get("player"),
                     **compare(attempts, min_n)})
    maps.sort(key=lambda m: (-m["n_attempts"], m["map"] or ""))
    return {"n_runs": len(rows), "n_maps": len(maps),
            "n_repeated": sum(1 for m in maps if m["n_attempts"] >= MIN_ATTEMPTS),
            "maps": maps}


# ----------------------------------------------------------- presentation ----

def describe(block, only_repeated=True):
    """Human-readable lines for the cross-attempt block."""
    lines = [f"CROSS-ATTEMPT ({block['n_runs']} runs over {block['n_maps']} maps, "
             f"{block['n_repeated']} with repeats)"]
    for mp in block["maps"]:
        if only_repeated and mp["n_attempts"] < MIN_ATTEMPTS:
            continue
        lines.append(f"  {mp['map']}  ({mp['n_attempts']} attempts)")
        for a in mp["attempts"]:
            when = (a["played_at"] or "")[:16].replace("T", " ")
            dup = f"  (+{len(a['duplicates'])} duplicate export)" if a["duplicates"] else ""
            lines.append(f"    {when:16s} {a['tag'] or '-':14s} acc "
                         f"{(a['accuracy'] or 0) * 100:5.1f}%  n={a['n_objects']}"
                         + ("" if a["trustworthy"] else "  [!untrusted]") + dup)
        for label, key in (("families", "families"), ("shapes", "shapes")):
            rows = [f for f in mp.get(key) or [] if f.get("reported")]
            hidden = [f for f in mp.get(key) or []
                      if not f.get("reported") and f.get("rates")]
            if not rows and not hidden:
                continue
            lines.append(f"    {label}:")
            for f in rows:
                rates = "  ".join(f"{r * 100:5.1f}%" for r in f["rates"])
                flag = ""
                if f.get("stable_weakness"):
                    flag = "  <-- consistent weakness"
                elif f.get("volatile") and f.get("solid"):
                    flag = "  <-- swings"
                elif not f.get("solid"):
                    flag = "  (thin)"
                lines.append(f"      {f['name']:26s} {rates}  "
                             f"({f['delta_pts']:+.1f} pts)" + flag)
            if hidden:
                hidden.sort(key=lambda f: -min(f["n"]))
                shown = ", ".join(f"{f['name']} (n={min(f['n'])})"
                                  for f in hidden[:6])
                more = (f", and {len(hidden) - 6} more"
                        if len(hidden) > 6 else "")
                lines.append(f"      not compared (under {MIN_ATTEMPT_N} objects in "
                             f"some attempt): {shown}{more}")
        if mp["verdict"]:
            lines.append(f"    verdict: {mp['verdict']}")
    return lines
