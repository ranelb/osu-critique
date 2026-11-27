"""Per-class miss rates on real replays: does a pattern class cost the player?

Joins every ``out/*_objects.json`` (per-object results) with the map's own pattern classes
(``metrics.classes.label``) and rosu-pp section strains, then pools them with
``metrics.class_miss.pool``. The class of an object comes from the map alone; the result
comes from the replay. Same code path as the per-run ``class_miss`` block, so there is no
second labeller here.

    python scripts/replay_join.py [--out DIR] [--index out/index.sqlite] [--min-n 30] [--boot 400] [--json FILE]

Contrasts are against the rest of the same map (raw, same leg distance x tempo, same
aim x speed strain cell); intervals bootstrap over maps. Runs with speed/HR/EZ/relax mods,
failed or untrusted runs are skipped (their clock or geometry differs from the .osu).
A map played several times is one cluster. Read-only; writes nothing unless --json is given.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import warnings
from collections import defaultdict
from pathlib import Path

from osu_critique.io.beatmap import build_objects, circle_radius
from osu_critique.metrics import class_miss, classes
from osu_critique.metrics.difficulty import attach_section_strains, section_strains
from osu_critique.metrics.structure import beat_at_fn

SKIP_MODS = ("DT", "NC", "HT", "DC", "HR", "EZ", "RX", "AP", "TD")


def map_rows(path):
    import slider
    bm = slider.Beatmap.from_path(path)
    r = circle_radius(bm.cs())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        objs = build_objects(bm, 1.0)
    classes.label(objs, r, beat_at_fn(bm, 1.0))
    attach_section_strains(objs, section_strains(path, 1.0, ""))
    return objs


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
    cache, by_map = {}, defaultdict(list)
    runs = skipped = 0
    for f in sorted(out.glob("*_objects.json")):
        d = json.load(open(f))
        md5 = d.get("beatmap_md5")
        mods = d.get("mod_string") or "NM"
        meta = {}
        mf = f.with_name(f.name.replace("_objects.json", "_metrics.json"))
        if mf.exists():
            meta = json.load(open(mf))
        if (any(m in mods for m in SKIP_MODS) or md5 not in paths or not Path(paths[md5]).exists()
                or meta.get("failed_play") or not (meta.get("trust") or {}).get("trustworthy")):
            skipped += 1
            continue
        if md5 not in cache:
            try:
                cache[md5] = map_rows(paths[md5])
            except Exception:
                cache[md5] = None
        base = cache[md5]
        recs = d["objects"]
        if base is None or len(recs) != len(base):
            skipped += 1
            continue
        runs += 1
        for rec in recs:
            row = dict(base[rec["i"]])
            row["result"] = rec.get("result")
            by_map[md5].append(row)
    print(f"runs joined {runs}, skipped {skipped}, maps {len(by_map)}", file=sys.stderr)
    res = class_miss.pool(by_map, min_objects=a.min_n, boot=a.boot)
    o = res["overall"]
    print(f"overall miss rate {o['miss']}/{o['n']} = {100 * o['rate']:.2f}% over {o['maps']} maps")

    def cell(v, ci):
        if v is None:
            return "n/a"
        s = f"{100 * v:+.2f}pp"
        return s + (f" [{100 * ci[0]:+.2f}, {100 * ci[1]:+.2f}]" if ci else "")

    print(f"{'class':28} {'n':>7} {'maps':>5} {'miss%':>6}  vs rest | same dist+tempo | same strain cell  (95% CI, maps resampled)")
    for r in sorted(res["classes"], key=lambda r: -(r["adj_strain"] or r["vs_rest"] or 0)):
        print(f"{r['class']:28} {r['n']:>7} {r['maps']:>5} {100 * r['rate']:>6.2f}  "
              f"{cell(r['vs_rest'], r['vs_rest_ci'])} | {cell(r['adj_stratum'], r['adj_stratum_ci'])} | "
              f"{cell(r['adj_strain'], r['adj_strain_ci'])}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
