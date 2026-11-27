"""Per-class miss rates: does a pattern class cost the player, beyond how hard it is?

Input is the per-object rows (``result`` plus the map-side class fields from
``metrics/classes.py`` and, when ``rosu-pp`` is installed, ``sec_aim`` / ``sec_speed``,
rosu-pp's strain of the 400 ms section the object sits in). Output is a block of classes,
each with its count, miss rate, Wilson interval and contrasts against the rest of the
same map:

    vs_rest      class rate minus the rate of every other object (raw; includes "wide
                 jumps are hard")
    adj_stratum  same, but only against other objects with the same leg distance x tempo
    adj_strain   same, but only against objects in the same aim-strain x speed-strain
                 tercile cell (rosu-pp's view of how hard the moment is)

A contrast is the n-weighted mean over matched cells of ``class rate - rest rate``; a cell
counts when it has at least ``MIN_REST`` other objects. ``None`` means "no cell could be
matched" and is never zero.

Gates (CLAUDE.md): a class is only reported when it has ``max(MIN_N, sequences.gate(N))``
objects, with ``MIN_N = 10`` (never a rate from n < 10) and the gate
``min(20, max(8, 3 % of objects))``; n is quoted with every rate. Spinners are not
population. One run is one map, so the per-run block carries Wilson intervals only;
:func:`pool` pools runs over many maps and bootstraps **clustered by map** (the unit that
actually varies), which is where the contrast intervals come from.

Everything is deterministic (the bootstrap is seeded).
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

from .classes import class_keys, stratum
from .sequences import gate as population_gate

MIN_N = 10          # never state a rate from fewer objects
MIN_REST = 5        # matched cell needs this many other objects to be a comparison
BINS = 3            # strain terciles


def wilson(k, n, z=1.96):
    """Wilson score interval for k of n (``(0.0, 0.0)`` for n == 0)."""
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


def min_n(n_objects):
    return max(MIN_N, math.ceil(population_gate(n_objects)))


def _population(rows):
    return [r for r in rows if r.get("kind") != "Spinner" and r.get("result") is not None]


def _edges(values):
    """Tercile edges of a list of numbers (``BINS - 1`` cut points)."""
    vs = sorted(values)
    if len(vs) < BINS * 3:
        return None
    return [vs[(len(vs) * q) // BINS] for q in range(1, BINS)]


def _bin(v, edges):
    return sum(v > e for e in edges)


def strain_cells(rows):
    """``{id(row): (aim_bin, speed_bin)}`` for rows that carry both strains."""
    have = [r for r in rows if r.get("sec_aim") is not None and r.get("sec_speed") is not None]
    ea = _edges([r["sec_aim"] for r in have])
    es = _edges([r["sec_speed"] for r in have])
    if ea is None or es is None:
        return {}
    return {id(r): (_bin(r["sec_aim"], ea), _bin(r["sec_speed"], es)) for r in have}


def _tally(rows, cellfn):
    """``{cell: [misses, n]}`` over rows with a cell."""
    out = defaultdict(lambda: [0, 0])
    for r in rows:
        c = cellfn(r)
        if c is not None:
            out[c][0] += r["result"] == "miss"
            out[c][1] += 1
    return out


def matched(cls_cells, all_cells):
    """``(contrast, n_used)``: mean over cells of class rate minus rest rate, class-n weighted."""
    num = den = 0.0
    for c, (k, n) in cls_cells.items():
        K, N = all_cells.get(c, (0, 0))
        if n and N - n >= MIN_REST:
            num += n * (k / n - (K - k) / (N - n))
            den += n
    return (num / den if den else None), int(den)


def _rest(k, n, K, N):
    return (k / n - (K - k) / (N - n)) if n and N > n else None


def _rate(k, n):
    return k / n if n else None


def build(rows, n_objects=None, unavailable=None):
    """The per-run block (``metrics["class_miss"]``).

    ``rows`` are object rows in play order. ``unavailable`` (a string) short-circuits to
    ``{"available": False, "reason": ...}`` -- used for Relax, where taps and therefore
    judged misses are not the player's.
    """
    if unavailable:
        return {"available": False, "reason": unavailable}
    pop = _population(rows)
    n_total = n_objects or len(pop)
    need = min_n(n_total)
    N = len(pop)
    K = sum(r["result"] == "miss" for r in pop)
    sc = strain_cells(pop)
    strat_all = _tally(pop, stratum)
    strain_all = _tally(pop, lambda r: sc.get(id(r)))
    members = defaultdict(list)
    for r in pop:
        for key in class_keys(r):
            members[key].append(r)
    out, held = [], 0
    for key in sorted(members):
        rs = members[key]
        n = len(rs)
        if n < need:
            held += 1
            continue
        k = sum(r["result"] == "miss" for r in rs)
        adj_s, ns = matched(_tally(rs, stratum), strat_all)
        adj_t, nt = matched(_tally(rs, lambda r: sc.get(id(r))), strain_all)
        lo, hi = wilson(k, n)
        out.append({
            "class": key, "n": n, "miss": k, "rate": round(k / n, 4),
            "ci": [round(lo, 4), round(hi, 4)],
            "vs_rest": _r4(_rest(k, n, K, N)),
            "adj_stratum": _r4(adj_s), "n_stratum": ns,
            "adj_strain": _r4(adj_t), "n_strain": nt,
        })
    lo, hi = wilson(K, N)
    return {
        "available": True,
        "n_population": N, "min_n": need,
        "overall": {"n": N, "miss": K, "rate": round(K / N, 4) if N else None,
                    "ci": [round(lo, 4), round(hi, 4)]},
        "controls": {"stratum": "leg distance x tempo",
                     "strain": "rosu-pp aim x speed section strain, terciles"
                               if sc else None},
        "classes": out,
        "held_back": held,
    }


def _r4(v):
    return None if v is None else round(v, 4)


# -------------------------------------------------------------------- pooling --

def _contrib(cls_cells, all_cells):
    """One map's ``(sum of n * diff, sum of n)`` for a contrast: the pooled value is the
    ratio of these sums, so resampling maps is just resampling pairs."""
    num = den = 0.0
    for c, (k, n) in cls_cells.items():
        K, N = all_cells.get(c, (0, 0))
        if n and N - n >= MIN_REST:
            num += n * (k / n - (K - k) / (N - n))
            den += n
    return num, den


def _map_summary(rows):
    """Per-map sufficient statistics: per class ``(k, n)`` and the contrast contributions."""
    pop = _population(rows)
    sc = strain_cells(pop)
    cellfns = {"vs_rest": lambda r: "all", "adj_stratum": stratum,
               "adj_strain": lambda r: sc.get(id(r))}
    base = {name: _tally(pop, fn) for name, fn in cellfns.items()}
    members = defaultdict(list)
    for r in pop:
        for key in class_keys(r):
            members[key].append(r)
    cls = {}
    for key, rs in members.items():
        cls[key] = {"k": sum(r["result"] == "miss" for r in rs), "n": len(rs),
                    **{name: _contrib(_tally(rs, fn), base[name])
                       for name, fn in cellfns.items()}}
    k = sum(r["result"] == "miss" for r in pop)
    return {"K": k, "N": len(pop), "cls": cls}


CONTRASTS = ("vs_rest", "adj_stratum", "adj_strain")


def pool(by_map, min_objects=30, boot=400, seed=1):
    """Pool object rows over runs and maps; contrast CIs bootstrapped clustered by map.

    ``by_map``: ``{map_id: [rows of every run of that map]}`` (a second run of a map is
    the same cluster, not new evidence). Returns ``{"overall", "classes"}``; a class
    needs ``min_objects`` objects and 5 maps. Intervals are the 2.5 / 97.5 percentiles of
    ``boot`` resamples of the maps that carry the class (null when fewer than 40 draws
    are defined). ``ci_naive`` is the per-object Wilson interval, which ignores that
    objects of one map share a fate, and is shown only for comparison.
    """
    import numpy as np

    summaries = {m: _map_summary(rows) for m, rows in sorted(by_map.items())}
    K = sum(s["K"] for s in summaries.values())
    N = sum(s["N"] for s in summaries.values())
    by_class = defaultdict(list)
    for m, s in summaries.items():
        for key, c in s["cls"].items():
            by_class[key].append(c)
    rng = np.random.default_rng(seed)
    out = []
    for key in sorted(by_class):
        cs = by_class[key]
        k, n = sum(c["k"] for c in cs), sum(c["n"] for c in cs)
        if n < max(MIN_N, min_objects) or len(cs) < 5:
            continue
        row = {"class": key, "n": n, "maps": len(cs), "miss": k, "rate": round(k / n, 4),
               "ci_naive": [round(x, 4) for x in wilson(k, n)]}
        idx = rng.integers(0, len(cs), size=(boot, len(cs)))
        for name in CONTRASTS:
            num = np.array([c[name][0] for c in cs])
            den = np.array([c[name][1] for c in cs])
            pt = num.sum() / den.sum() if den.sum() else None
            ci = None
            if pt is not None:
                dd = den[idx].sum(axis=1)
                ok = dd > 0
                draws = np.sort(num[idx].sum(axis=1)[ok] / dd[ok])
                if len(draws) >= 40:
                    ci = [round(float(draws[int(.025 * len(draws))]), 4),
                          round(float(draws[max(0, int(.975 * len(draws)) - 1)]), 4)]
            row[name] = _r4(pt)
            row[name + "_ci"] = ci
        out.append(row)
    return {"overall": {"n": N, "miss": K, "rate": round(K / N, 4) if N else None,
                        "maps": len(summaries)},
            "classes": out}
