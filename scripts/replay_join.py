"""Per-class miss rates on real replays: does a pattern class cost the player?

Joins every ``out/*_objects.json`` (per-object results) with the map's own geometry
classes (``metrics.walks``, ``curves``, ``geometry``, ``legs`` descriptors). The class of
an object comes from the map alone; the result comes from the replay.

    python scripts/replay_join.py [--out DIR] [--index out/index.sqlite] [--min-n 30] [--boot 400]

Numbers: miss rate with a Wilson interval, and the **within-map contrast** - the class
rate minus the miss rate of the *other* objects of the same map, averaged over maps with a
map-clustered bootstrap. Runs with speed/HR/EZ/relax mods are skipped (their geometry or
clock differs from the .osu). Read-only; writes nothing unless --json is given.
"""
from __future__ import annotations

import argparse, json, math, random, sqlite3, sys, warnings
from collections import defaultdict
from pathlib import Path

from osu_critique.io.beatmap import build_objects, circle_radius
from osu_critique.metrics import curves, legs, walks

SKIP_MODS = ("DT", "NC", "HT", "DC", "HR", "EZ", "RX", "AP", "TD")


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def classes(path):
    import slider
    bm = slider.Beatmap.from_path(path)
    r = circle_radius(bm.cs())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        objs = build_objects(bm, 1.0)
    cls = [set() for _ in objs]
    for mod, src in (("walk", walks.find(objs, r)), ("curve", curves.find(objs, r))):
        for s in src:
            for i in range(s["start"], s["end"] + 1):
                cls[i].add(f"{mod}:{s['shape']}")
    rows = legs.legs(objs, r)
    for i, lg in enumerate(rows):
        if lg:
            cls[i].add(f"leg:{lg['dist']}/{lg['flow']}")
            cls[i].add(f"dist:{lg['dist']}")
    base = [f"{lg['dist']}/{lg['tempo']}" if lg else None for lg in rows]
    return objs, cls, base


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--index", default=None)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--boot", type=int, default=400)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    out = Path(a.out)
    conn = sqlite3.connect(a.index or out / "index.sqlite")
    paths = dict(conn.execute("select beatmap_md5, map_path from beatmaps where map_path is not null"))
    cache, per_map = {}, defaultdict(lambda: defaultdict(lambda: [0, 0]))   # md5 -> class -> [miss, n]
    allmap = defaultdict(lambda: [0, 0])
    cell = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    cellc = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    runs = skipped = 0
    for f in sorted(out.glob("*_objects.json")):
        d = json.load(open(f))
        md5 = d.get("beatmap_md5")
        mods = d.get("mod_string") or "NM"
        if any(m in mods for m in SKIP_MODS) or md5 not in paths or not Path(paths[md5]).exists():
            skipped += 1
            continue
        if md5 not in cache:
            try:
                cache[md5] = classes(paths[md5])
            except Exception:
                cache[md5] = None
        if cache[md5] is None:
            skipped += 1
            continue
        objs, cls, base = cache[md5]
        recs = d["objects"]
        if len(recs) != len(objs):
            skipped += 1
            continue
        runs += 1
        for rec in recs:
            miss = 1 if rec.get("result") == "miss" else 0
            allmap[md5][0] += miss
            allmap[md5][1] += 1
            b = base[rec["i"]]
            if b:
                cell[md5][b][0] += miss
                cell[md5][b][1] += 1
            for c in cls[rec["i"]]:
                per_map[md5][c][0] += miss
                per_map[md5][c][1] += 1
                if b:
                    cellc[md5][(c, b)][0] += miss
                    cellc[md5][(c, b)][1] += 1
    print(f"runs joined {runs}, skipped {skipped}, maps {len(allmap)}", file=sys.stderr)
    classes_seen = defaultdict(lambda: [0, 0])
    for m in per_map.values():
        for c, (k, n) in m.items():
            classes_seen[c][0] += k
            classes_seen[c][1] += n
    tot_k = sum(v[0] for v in allmap.values()); tot_n = sum(v[1] for v in allmap.values())
    print(f"overall miss rate {tot_k}/{tot_n} = {100*tot_k/tot_n:.2f}%")
    rng = random.Random(1)

    def contrast(c, maps):
        num = den = 0.0
        for m in maps:
            k, n = per_map[m].get(c, (0, 0))
            K, N = allmap[m]
            if n and N - n:
                num += n * (k / n - (K - k) / (N - n))
                den += n
        return num / den if den else None

    def adjusted(c, maps):
        """Same map, same leg distance and tempo: class objects vs the other objects there."""
        num = den = 0.0
        for m in maps:
            for (cc, b), (k, n) in cellc[m].items():
                if cc != c:
                    continue
                K, N = cell[m][b]
                if n and N - n >= 5:
                    num += n * (k / n - (K - k) / (N - n))
                    den += n
        return num / den if den else None

    res = []
    for c, (k, n) in classes_seen.items():
        if n < a.min_n:
            continue
        maps = [m for m in per_map if c in per_map[m]]
        pt = contrast(c, maps)
        bs = sorted(x for x in (contrast(c, [rng.choice(maps) for _ in maps]) for _ in range(a.boot)) if x is not None)
        lo, hi = (bs[int(.025 * len(bs))], bs[int(.975 * len(bs)) - 1]) if len(bs) > 20 else (None, None)
        w = wilson(k, n)
        adj = adjusted(c, maps)
        ab = sorted(x for x in (adjusted(c, [rng.choice(maps) for _ in maps]) for _ in range(a.boot)) if x is not None)
        alo, ahi = (ab[int(.025 * len(ab))], ab[int(.975 * len(ab)) - 1]) if len(ab) > 20 else (None, None)
        res.append({"adj": adj, "adj_ci": (alo, ahi), "class": c, "n": n, "maps": len(maps), "miss": k, "rate": k / n, "wilson": w,
                    "contrast": pt, "ci": (lo, hi)})
    res.sort(key=lambda r: -(r["contrast"] or 0))
    print(f"{'class':28} {'n':>7} {'maps':>5} {'miss%':>6} {'wilson':>13} {'vs rest of map':>16}  95% CI (maps resampled)   same dist+tempo: adj   CI")
    for r in res:
        ci = f"[{100*r['ci'][0]:+.2f}, {100*r['ci'][1]:+.2f}]" if r["ci"][0] is not None else "n/a"
        adjs = ("n/a" if r["adj"] is None or r["adj_ci"][0] is None else
                f"{100*r['adj']:+.2f}pp [{100*r['adj_ci'][0]:+.2f}, {100*r['adj_ci'][1]:+.2f}]")
        print(f"{r['class']:28} {r['n']:>7} {r['maps']:>5} {100*r['rate']:>6.2f} "
              f"{100*r['wilson'][0]:>5.1f}-{100*r['wilson'][1]:<5.1f} {100*(r['contrast'] or 0):>+15.2f}pp  {ci}   {adjs}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
