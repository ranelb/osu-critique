"""Held-out validation of the recommender: map-side dimensions and the bucket rules.

    python scripts/validate_recommend.py --out DIR [--player NAME] [--boot 400]

``DIR`` holds an ``index.sqlite`` that has runs *and* a ``library scan`` at the current
``FEATURE_VERSION`` (work on a copy: this script only reads, but the scan writes).
Nothing personal is printed beyond counts and rates; nothing is written.

1. **Dimensions** (does the skill profile predict runs it has not seen?). Runs are cut by
   time; the profile is fitted on the early part and asked about the late part:

   * ``rho``: Spearman between a held-out run's similarity to the fitted weaknesses
     (exactly the scorer's number) and its held-out miss-rate residual against the
     *training* band baseline. Positive means "maps the profile calls like your
     weaknesses really do cost you more". CI is a bootstrap over *maps* (a map's runs are
     not independent).
   * ``gap``: for each fitted weakness, the held-out excess-miss gap between its bad and
     good half, at the training split value, with n per side.
   * ``agree``: share of all dimensions whose bad side in training is still the bad
     side held out.

   The legacy dimensions (spacing buckets and the stream detector) are scored the same way
   so the swap is a measured one.

2. **Buckets** (do the improver/maintain cut-offs predict anything?). Each run that had
   >= 2 earlier attempts at its map is a prediction target; the rule is applied to the
   history *before* it. The outcome is ``acc(run) - acc(latest earlier attempt)``. Be
   careful reading it: any "latest was bad" rule gains from regression to the mean, so
   improver is only credited for what it adds *over the non-improver group*, and only a
   monotone relation (gap vs gain) says anything about a cut-off.
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

from osu_critique import recommend as R

LEGACY = (
    ("sustained", "sustained density", lambda f: f["sustained_nps"]),
    ("stream", "stream share", lambda f: f["stream_share"]),
    ("jump", "jump spacing", lambda f: (f["jump_share"] or 0) + (f["bigjump_share"] or 0)),
    ("reversal", "sharp reversals", lambda f: f["anti_flow_share"]),
    ("slider", "slider density", lambda f: f["slider_ratio"]),
)


def ranks(x):
    x = np.asarray(x, float)
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    r[order] = np.arange(len(x))
    for v in np.unique(x):               # average ties
        m = x == v
        r[m] = r[m].mean()
    return r


def spearman(a, b):
    if len(a) < 10 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    return float(np.corrcoef(ranks(a), ranks(b))[0, 1])


def boot_ci(groups, stat, boot, seed=1):
    """Bootstrap ``stat(list of items)`` resampling whole groups (maps)."""
    keys = sorted(groups)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(boot):
        pick = rng.integers(0, len(keys), len(keys))
        v = stat([x for i in pick for x in groups[keys[i]]])
        if v is not None:
            out.append(v)
    if len(out) < 40:
        return None
    out.sort()
    return out[int(.025 * len(out))], out[max(0, int(.975 * len(out)) - 1)]


def fmt(v, d=3):
    return "n/a" if v is None else f"{v:+.{d}f}"


def fmt_ci(ci, d=3):
    return "" if ci is None else f" [{ci[0]:+.{d}f}, {ci[1]:+.{d}f}]"


def load(conn, dims, player):
    R.DIMENSIONS = dims
    rows = [dict(r) for r in conn.execute(R.LIBRARY_SQL)]
    values = {}
    for r in rows:
        v = R._dimension_values(r)
        v["sr"] = R._num(r["sr"])
        values[r["beatmap_md5"]] = v
    plays, stats = R._play_evidence(conn, player, values)
    return plays, stats


def evaluate_profile(plays, cut, boot):
    k = int(len(plays) * cut)
    train, test = plays[:k], plays[k:]
    profile = R.skill_profile(train, {}, "all")
    bands = R.miss_band_medians(train)
    rankings = {key: sorted(v for v in (p["values"].get(key) for p in train)
                            if v is not None) for key, _l, _f in R.DIMENSIONS}
    sims, res, by_map = [], [], defaultdict(list)
    for p in test:
        b = R._band_of(p["sr"], R.MISS_BAND) if p["sr"] is not None else None
        if p["miss_rate"] is None or b not in bands:
            continue
        _w, sim = R._similarity(profile["weaknesses"], p["values"], rankings)
        item = (sim, p["miss_rate"] - bands[b])
        sims.append(item[0]); res.append(item[1])
        by_map[p["beatmap_md5"]].append(item)
    rho = spearman(sims, res) if profile["weaknesses"] else None
    ci = (boot_ci(by_map, lambda it: spearman([x[0] for x in it], [x[1] for x in it]), boot)
          if rho is not None else None)
    gaps = []
    for w in profile["weaknesses"]:
        lo, hi = [], []
        for p in test:
            v = p["values"].get(w["key"])
            b = R._band_of(p["sr"], R.MISS_BAND) if p["sr"] is not None else None
            if v is None or p["miss_rate"] is None or b not in bands:
                continue
            (hi if v > w["split"] else lo).append(p["miss_rate"] - bands[b])
        bad, good = (hi, lo) if w["bad_side"] == "high" else (lo, hi)
        if len(bad) >= 10 and len(good) >= 10:
            gaps.append((w["key"], 100 * (st.fmean(bad) - st.fmean(good)), len(bad), len(good),
                         w["gap_pp"]))
    agree = []
    for e in profile["dimensions"]:
        lo = [p["miss_rate"] - bands[R._band_of(p["sr"], R.MISS_BAND)] for p in test
              if p["values"].get(e["key"]) is not None and p["miss_rate"] is not None
              and p["sr"] is not None and R._band_of(p["sr"], R.MISS_BAND) in bands
              and p["values"][e["key"]] <= e["split"]]
        hi = [p["miss_rate"] - bands[R._band_of(p["sr"], R.MISS_BAND)] for p in test
              if p["values"].get(e["key"]) is not None and p["miss_rate"] is not None
              and p["sr"] is not None and R._band_of(p["sr"], R.MISS_BAND) in bands
              and p["values"][e["key"]] > e["split"]]
        if len(lo) >= 10 and len(hi) >= 10:
            agree.append((st.fmean(hi) >= st.fmean(lo)) == (e["bad_side"] == "high"))
    return {"cut": cut, "train": len(train), "test": len(res), "weak": len(profile["weaknesses"]),
            "rho": rho, "ci": ci, "gaps": gaps,
            "agree": (sum(agree), len(agree))}


def parse(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def attempt_table(conn, player):
    """One record per run with >= 2 earlier judged attempts at the same map."""
    runs = conn.execute(
        "SELECT beatmap_md5, accuracy, failed, played_at, sr FROM runs WHERE player = ? "
        "AND accuracy IS NOT NULL AND is_relax = 0 ORDER BY played_at", (player,)).fetchall()
    hist = defaultdict(list)
    seen = []                                  # (band, accuracy) of every earlier run
    out = []
    for r in runs:
        prev = hist[r["beatmap_md5"]]
        band = R._band(R._num(r["sr"])) if r["sr"] is not None else None
        if len(prev) >= 2 and band is not None:
            accs = [a for b, a in seen if b == band]
            if len(accs) >= R.MIN_BAND_RUNS:
                latest = prev[-1]
                out.append({
                    "md5": r["beatmap_md5"], "acc": float(r["accuracy"]),
                    "latest": latest["accuracy"], "failed": latest["failed"],
                    "median": st.median(accs),
                    "days": (parse(r["played_at"]) - parse(latest["played_at"])).total_seconds() / 86400,
                    "i": len(out)})
        hist[r["beatmap_md5"]].append({"accuracy": float(r["accuracy"]), "failed": bool(r["failed"]),
                                       "played_at": r["played_at"]})
        seen.append((band, float(r["accuracy"])))
    return out


def group_stat(rows, boot):
    by = defaultdict(list)
    for x in rows:
        by[x["md5"]].append(100 * (x["acc"] - x["latest"]))
    gains = [g for v in by.values() for g in v]
    if not gains:
        return "n=0"
    ci = boot_ci(by, lambda it: st.fmean(it) if it else None, boot)
    return f"n={len(gains):>5} maps={len(by):>4} gain {st.fmean(gains):+.2f}pp{fmt_ci(ci, 2)}"


def buckets(conn, player, boot):
    rows = attempt_table(conn, player)
    print(f"\n== buckets: {len(rows)} runs with >=2 earlier attempts and a band median ==")
    cut = int(len(rows) * 0.7)
    for name, part in (("all", rows), ("early 70% (choose here)", rows[:cut]),
                       ("late 30% (held out)", rows[cut:])):
        print(f"\n-- {name} --  gain = acc(run) - acc(latest earlier attempt), pp")
        print("improver rule (latest below the band median by more than `gap`; failed counts):")
        for gap in (None, 0.0, 0.01, 0.03, 0.05):
            if gap is None:
                sel = [x for x in part if x["failed"]]
                label = "latest failed          "
            else:
                sel = [x for x in part if x["failed"] or x["latest"] < x["median"] - gap]
                label = f"gap > {100 * gap:>3.0f}pp            "
            print(f"  {label} {group_stat(sel, boot)}")
        non = [x for x in part if not x["failed"] and x["latest"] >= x["median"]]
        print(f"  not improver (>= median)  {group_stat(non, boot)}")
        gaps = [x["median"] - x["latest"] for x in part]
        gains = [x["acc"] - x["latest"] for x in part]
        print(f"  Spearman(gap below median, gain) = {fmt(spearman(gaps, gains))}  (n={len(part)})")
        print("maintain rule (latest at/above median; days since the latest attempt):")
        ok = [x for x in part if not x["failed"] and x["latest"] >= x["median"]]
        for lo, hi in ((0, 7), (7, 30), (30, 90), (90, 100000)):
            sel = [x for x in ok if lo <= x["days"] < hi]
            print(f"  {lo:>3}-{hi if hi < 100000 else 'inf':>3} days      {group_stat(sel, boot)}")
        print(f"  Spearman(days, gain) = {fmt(spearman([x['days'] for x in ok], [x['acc'] - x['latest'] for x in ok]))}  (n={len(ok)})")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--player", default=None)
    ap.add_argument("--boot", type=int, default=300)
    ap.add_argument("--cuts", type=float, nargs="*", default=[0.6, 0.7, 0.8, 0.9])
    ap.add_argument("--skip-buckets", action="store_true")
    a = ap.parse_args(argv)
    conn = sqlite3.connect(Path(a.out) / "index.sqlite")
    conn.row_factory = sqlite3.Row
    player = a.player or R.default_player(conn)
    for name, dims in (("legacy", LEGACY), ("rosu-pp + classes", R.DIMENSIONS)):
        plays, stats = load(conn, dims, player)
        print(f"\n== dimensions: {name}: {len(plays)} plays, {stats['no_map']} unmapped ==")
        for cut in a.cuts:
            e = evaluate_profile(plays, cut, a.boot)
            gaps = "; ".join(f"{k} {g:+.2f}pp (n={nb}/{ng}, fitted {fit:+.2f})"
                             for k, g, nb, ng, fit in e["gaps"]) or "-"
            print(f"cut {cut:.1f} train {e['train']:>4} test {e['test']:>4} weaknesses {e['weak']} "
                  f"rho {fmt(e['rho'])}{fmt_ci(e['ci'])} "
                  f"agree {e['agree'][0]}/{e['agree'][1]}\n     held-out gaps: {gaps}")
    if not a.skip_buckets:
        buckets(conn, player, a.boot)


if __name__ == "__main__":
    main()
