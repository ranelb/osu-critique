"""Map recommendations: what to play next, and the evidence for saying so.

Three inputs, one deterministic answer:

- **the runs** in the index (accuracy, misses, when you played what) — the
  evidence of what you actually do;
- **``library_beatmaps``** (``osu-critique library scan``) — what every installed
  map is made of, played or not;
- **``out/blacklist.json``** — the maps you never want suggested again.

Weaknesses are read off **map material**, not off per-object buckets. That is a
deliberate unit change: the per-object view (``metrics/profile``) describes one
play's objects, while a recommendation has to filter the *library*, and the only
features a never-played map has are the map-side ones. So the axis is the same
on both sides of the comparison, and no "family -> feature" translation can
drift.

A weakness is a dimension where the worse half of your plays loses at least
:data:`WEAKNESS_RATIO` times the accuracy of the better half *and* at least
:data:`WEAKNESS_GAP_PP` percentage points, with :data:`MIN_SIDE` runs per side.
The halves are a median split of your own corpus, so the thresholds calibrate
to you; the split itself is quoted in the output, never hidden.

Buckets, mutually exclusive:

``new``
    never played by this player.
``improver``
    played, at least two attempts, and the latest attempt is >=3 pp of accuracy
    below the median of your runs in the same 0.25-star band (or failed). The
    card carries the proof: your best here, that band median, the last attempt.
``maintain``
    at or above the band median, last played >=30 days ago, inside the comfort
    band.

Everything is deterministic: no model, no timestamps in the output, ties broken
by md5. ``recommend --json`` is the testable surface.
"""
from __future__ import annotations

import bisect
import json
import math
import statistics as st
from datetime import datetime, timedelta

from . import blacklist, index

#: candidate gates (see docs/recommend.md)
MIN_LENGTH_MS = 40_000
MAX_LENGTH_MS = 270_000
MIN_OBJECTS = 120
#: hard difficulty band around the comfort rating, in stars
BAND = 1.0
#: the profile reads this much history, or everything if that is too thin
WINDOW_DAYS = 90
MIN_WINDOW_RUNS = 60
#: runs needed on each side of a dimension's median split
MIN_SIDE = 20
#: runs needed in a 0.25-star band before it gets a median
MIN_BAND_RUNS = 5
#: improver: accuracy gap below the band median, in accuracy points (0..1)
IMPROVER_GAP = 0.03
#: maintain: days since the last attempt
MAINTAIN_DAYS = 30
#: where the difficulty fit peaks above the comfort rating, at stretch = 1
STRETCH_PEAK = 0.6
#: weakness gate: the worse half's *excess miss rate* (miss rate minus your own
#: median miss rate at that star rating) against the better half's
WEAKNESS_RATIO = 1.5
WEAKNESS_GAP_PP = 0.5
#: two dimensions this correlated describe the same skill; only the stronger is
#: reported (e.g. "few streams" and "few sliders" are both "spaced circles")
WEAKNESS_CORRELATION = 0.9
#: floor for the excess ratio, in pp: a near-baseline good half must not make
#: every small difference look infinite
EXCESS_FLOOR_PP = 0.05
#: the star band the miss baseline is taken in, and runs it needs to exist
MISS_BAND = 0.5
MIN_MISS_BAND_RUNS = 8

#: map-material dimensions. ``jump`` sums jump and bigjump spacing, which is the
#: same physical skill at two scales.
DIMENSIONS = (
    ("sustained", "sustained density", lambda f: f["sustained_nps"]),
    ("stream", "stream share", lambda f: f["stream_share"]),
    ("jump", "jump spacing", lambda f: _add(f["jump_share"], f["bigjump_share"])),
    ("reversal", "sharp reversals", lambda f: f["anti_flow_share"]),
    ("slider", "slider density", lambda f: f["slider_ratio"]),
)


def _add(a, b):
    return (a or 0.0) + (b or 0.0)


def _num(value):
    """``sqlite3.Row``/dict value as float, or None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now() -> datetime:
    return datetime.now()


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _days_since(value) -> float | None:
    when = _parse_time(value)
    return None if when is None else (_now() - when).total_seconds() / 86400.0


# --------------------------------------------------------------- the player --

def default_player(conn) -> str | None:
    """The player the dashboard is about: the most-run name in the corpus.

    Never a hardcoded name — a shipped tool must not assume it is the author's
    machine. Ties fall back to the most recent play.
    """
    row = conn.execute(
        "SELECT player, COUNT(*) AS n, MAX(played_at) AS last FROM runs "
        "WHERE player IS NOT NULL AND player != '' "
        "GROUP BY player ORDER BY n DESC, last DESC LIMIT 1").fetchone()
    return row["player"] if row else None


# ------------------------------------------------------------- the evidence --

def _dimension_values(feats: dict) -> dict:
    """The dimension inputs straight off a ``library_beatmaps`` row, as a dict.

    Columns, not ``features_json``: the scorer only needs these numbers, and
    parsing 5 000 JSON blobs per call would be the difference between a page and
    a wait.
    """
    values = {key: _num(fn(feats)) for key, _label, fn in DIMENSIONS}
    values["sustained_share"] = _num(feats.get("sustained_share"))
    return values


def _play_evidence(conn, player, values_by_md5) -> tuple[list, dict]:
    """One row per run that can speak about skill, with its map's features.

    Relax/autopilot runs are dropped: the game taps, so a miss there is not
    evidence about your tapping. Runs on maps the library scan does not cover
    (uninstalled, unparsable) cannot be attached to a material and are dropped
    too — counted, never guessed at.

    The outcome is the **miss rate** (misses / objects), not accuracy: accuracy
    is saturated by a handful of 100s on a short map, while a miss is an
    unambiguous failure and the thing a player actually wants fewer of. Each run
    then gets its *residual* — miss rate minus your own median miss rate in the
    same half-star band — so "harder map" cannot masquerade as "wrong material".
    """
    rows = conn.execute(
        "SELECT beatmap_md5, accuracy, is_relax, failed, played_at, sr, "
        "n_objects, counts_detected_json "
        "FROM runs WHERE player = ? AND accuracy IS NOT NULL "
        "ORDER BY played_at", (player,)).fetchall()
    plays, stats = [], {"runs": 0, "relax": 0, "no_map": 0, "no_misses": 0}
    for row in rows:
        stats["runs"] += 1
        if row["is_relax"]:
            stats["relax"] += 1
            continue
        values = values_by_md5.get(row["beatmap_md5"])
        if values is None:
            stats["no_map"] += 1
            continue
        sr = _num(row["sr"]) if row["sr"] is not None else values["sr"]
        miss_rate = _miss_rate(row["n_objects"], row["counts_detected_json"])
        if miss_rate is None:
            stats["no_misses"] += 1
        plays.append({
            "beatmap_md5": row["beatmap_md5"],
            "played_at": row["played_at"],
            "accuracy": float(row["accuracy"]),
            "miss_rate": miss_rate,
            "failed": bool(row["failed"]),
            "sr": sr,
            "values": {k: v for k, v in values.items() if k != "sr"},
        })
    return plays, stats


def _miss_rate(n_objects, counts_json) -> float | None:
    try:
        counts = json.loads(counts_json or "{}")
        miss = float(counts.get("miss") or 0)
    except (ValueError, TypeError):
        return None
    if not n_objects:
        return None
    return miss / float(n_objects)


def _window(plays: list, window_days: int = WINDOW_DAYS) -> tuple[list, str]:
    """Recent history, unless that is too thin to say anything — then all of it."""
    cutoff = (_now() - timedelta(days=window_days)).isoformat()
    recent = [p for p in plays if (p["played_at"] or "") >= cutoff]
    if len(recent) >= MIN_WINDOW_RUNS:
        return recent, f"{window_days}d"
    return plays, "all"


def _median(values):
    return float(st.median(values)) if values else None


def _band_of(value, width):
    return round(float(value) / width) * width


def miss_band_medians(plays: list) -> dict:
    """``{half-star band: median miss rate}`` — the baseline each run is scored against.

    Wider bands than the accuracy medians (0.5 vs 0.25 stars) because miss rates
    are sparser: a band needs :data:`MIN_MISS_BAND_RUNS` runs before it counts.
    """
    buckets: dict[float, list] = {}
    for p in plays:
        if p["sr"] is None or p["miss_rate"] is None:
            continue
        buckets.setdefault(_band_of(p["sr"], MISS_BAND), []).append(p["miss_rate"])
    return {band: st.median(rates) for band, rates in buckets.items()
            if len(rates) >= MIN_MISS_BAND_RUNS}


def _correlation(a_pairs, b_pairs):
    """Pearson r over the runs where both dimensions are defined, or None."""
    shared = [(va, vb) for va, vb in ((a_pairs.get(md5), b_pairs.get(md5))
                                     for md5 in a_pairs.keys() & b_pairs.keys())
              if va is not None and vb is not None]
    if len(shared) < 10:
        return None
    xs, ys = zip(*shared)
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    try:
        return st.correlation(xs, ys)
    except (ValueError, ZeroDivisionError):
        return None


def skill_profile(plays: list, stats: dict, window: str,
                  window_days: int = WINDOW_DAYS) -> dict:
    """Weaknesses and strengths over the map-material dimensions.

    For every dimension the plays are split at the dimension's median; each
    half's *excess* miss rate (against the same-star baseline) is compared. Both
    halves and the split point are reported, so the page can show the contrast
    it used instead of a verdict without a denominator.
    """
    bands = miss_band_medians(plays)
    candidates, entries, by_key = [], [], {}
    for key, label, _fn in DIMENSIONS:
        pairs = [(p["values"][key], p, p["miss_rate"]
                  - bands[_band_of(p["sr"], MISS_BAND)]) for p in plays
                 if p["values"].get(key) is not None and p["miss_rate"] is not None
                 and p["sr"] is not None
                 and _band_of(p["sr"], MISS_BAND) in bands]
        if len(pairs) < 2 * MIN_SIDE:
            continue
        by_key[key] = {p["beatmap_md5"] + str(p["played_at"]): p["values"][key]
                       for _v, p, _e in pairs}
        median = st.median(v for v, _p, _e in pairs)
        low = [excess for v, _p, excess in pairs if v <= median]
        high = [excess for v, _p, excess in pairs if v > median]
        if len(low) < MIN_SIDE or len(high) < MIN_SIDE:
            continue
        excess_low, excess_high = st.fmean(low), st.fmean(high)
        miss_low = _mean_miss([p for v, p, _e in pairs if v <= median])
        miss_high = _mean_miss([p for v, p, _e in pairs if v > median])
        bad_side = "high" if excess_high >= excess_low else "low"
        better, worse = sorted((excess_low, excess_high))
        gap_pp = 100.0 * (worse - better)
        entry = {
            "key": key,
            "label": label,
            "split": round(median, 4),
            "bad_side": bad_side,
            "excess_bad_pp": round(100.0 * worse, 2),
            "excess_good_pp": round(100.0 * better, 2),
            "miss_bad_pct": round(100.0 * (miss_high if bad_side == "high" else miss_low), 2),
            "miss_good_pct": round(100.0 * (miss_low if bad_side == "high" else miss_high), 2),
            "gap_pp": round(gap_pp, 2),
            "ratio": round((100.0 * worse + EXCESS_FLOOR_PP)
                           / (100.0 * max(0.0, better) + EXCESS_FLOOR_PP), 2),
            "n_bad": len(high) if bad_side == "high" else len(low),
            "n_good": len(low) if bad_side == "high" else len(high),
        }
        entries.append(entry)
        if gap_pp >= WEAKNESS_GAP_PP and entry["ratio"] >= WEAKNESS_RATIO:
            candidates.append(entry)

    # strongest first; drop a dimension that is just another name for one already
    # reported (stream share and slider density both describe "spaced circles")
    candidates.sort(key=lambda e: (-e["gap_pp"], e["key"]))
    weaknesses: list = []
    for entry in candidates:
        redundant = False
        for kept in weaknesses:
            r = _correlation(by_key.get(entry["key"], {}), by_key.get(kept["key"], {}))
            if r is not None and abs(r) >= WEAKNESS_CORRELATION:
                entry["redundant_with"] = kept["key"]
                redundant = True
                break
        if not redundant:
            weaknesses.append(entry)
    top_gap = weaknesses[0]["gap_pp"] if weaknesses else 0.0
    for entry in weaknesses:
        entry["weight"] = round(entry["gap_pp"] / top_gap, 4) if top_gap else 0.0

    weak_keys = {w["key"] for w in weaknesses}
    strengths = sorted((e for e in entries if e["key"] not in weak_keys),
                       key=lambda e: (e["excess_good_pp"], e["key"]))

    srs = [p["sr"] for p in plays if p["sr"] is not None]
    return {
        "window": window,
        "window_days": window_days,
        "n_runs": len(plays),
        "excluded_relax": stats.get("relax", 0),
        "unmapped_runs": stats.get("no_map", 0),
        "comfort_sr": round(_median(srs), 3) if srs else None,
        "miss_basis": "miss rate minus your own median miss rate in the same "
                      f"{MISS_BAND}★ band",
        "weaknesses": weaknesses[:3],
        "strengths": [
            {"key": e["key"], "label": e["label"],
             "miss_pct": e["miss_good_pct"], "excess_pp": e["excess_good_pp"],
             "n": e["n_good"]}
            for e in strengths[:2]
        ],
    }


def _mean_miss(plays):
    rates = [p["miss_rate"] for p in plays if p["miss_rate"] is not None]
    return float(st.fmean(rates)) if rates else 0.0


def _band(sr) -> float | None:
    if sr is None:
        return None
    return round(float(sr) * 4.0) / 4.0


def band_medians(plays: list) -> dict:
    """``{0.25-star band: median accuracy}`` for bands with enough runs."""
    buckets: dict[float, list] = {}
    for p in plays:
        band = _band(p["sr"])
        if band is not None:
            buckets.setdefault(band, []).append(p["accuracy"])
    return {band: st.median(accs) for band, accs in buckets.items()
            if len(accs) >= MIN_BAND_RUNS}


# ------------------------------------------------------------- candidates --

def _pct_rank(values: list, value: float) -> float:
    """Where ``value`` sits in ``values``: 0..1, ties take the lower rank."""
    if not values:
        return 0.5
    i = bisect.bisect_left(values, value)
    return i / len(values)


def _material(values: dict) -> str:
    """The phrase a card uses for what the map mostly is."""
    if (values.get("sustained") is not None and values["sustained"] >= 8.0
            and (values.get("sustained_share") or 0.0) >= 0.5):
        return "sustained stream"
    if values.get("stream") is not None and values["stream"] >= 0.5:
        return "mostly streams"
    if _add(values.get("jump"), 0.0) >= 0.6:
        return "jump spacing"
    if values.get("reversal") is not None and values["reversal"] >= 0.35:
        return "sharp reversals"
    if values.get("slider") is not None and values["slider"] >= 0.5:
        return "slider-heavy"
    return "mixed spacing"


def _clock(ms) -> str:
    total = int(round((ms or 0) / 1000.0))
    return f"{total // 60}:{total % 60:02d}"


def build(outdir, player: str | None = None, limit: int = 6,
          stretch: float = 0.5, buckets=None, use_blacklist: bool = True,
          conn=None) -> dict:
    """The whole recommendation, as one JSON-serialisable dict."""
    own = conn is None
    conn = conn or index.open_readonly(outdir)
    if conn is None:
        return {"player": player, "error": "no index yet — run `osu-critique index`",
                "recommendations": []}
    try:
        return _build(conn, outdir, player, limit, stretch, buckets, use_blacklist)
    finally:
        if own:
            conn.close()


def _build(conn, outdir, player, limit, stretch, buckets, use_blacklist) -> dict:
    player = player or default_player(conn)
    library_rows = [dict(r) for r in conn.execute(
        "SELECT * FROM library_beatmaps WHERE mode = 0")]
    if not library_rows:
        # an empty table is not "no good maps", it is "never scanned" — and
        # `index --rebuild` deletes the DB file, which takes this with it
        return {"player": player, "error": "no library scan — run "
                "`osu-critique library scan` (it is derived, and "
                "`index --rebuild` drops it)", "recommendations": [],
                "skills": {}}
    values_by_md5 = {}
    for row in library_rows:
        values = _dimension_values(row)
        values["sr"] = _num(row["sr"])
        values_by_md5[row["beatmap_md5"]] = values

    plays, stats = _play_evidence(conn, player, values_by_md5)
    windowed, window = _window(plays)
    profile = skill_profile(windowed, stats, window)
    bands = band_medians(plays)
    comfort = profile["comfort_sr"]

    # per-map attempt history for this player. `history` holds the attempts that
    # can be judged (no Relax); `played_any` is every map you touched, so a map
    # played only in Relax is *not* offered as "new" — it just cannot be
    # classified, and saying "never played" about it would be a lie.
    history: dict[str, list] = {}
    played_any = set()
    for row in conn.execute(
            "SELECT beatmap_md5, accuracy, failed, played_at, is_relax FROM runs "
            "WHERE player = ? ORDER BY played_at", (player,)):
        played_any.add(row["beatmap_md5"])
        if row["is_relax"] or row["accuracy"] is None:
            continue
        history.setdefault(row["beatmap_md5"], []).append({
            "played_at": row["played_at"],
            "accuracy": float(row["accuracy"]),
            "failed": bool(row["failed"]),
        })

    blocked = blacklist.load(outdir) if use_blacklist else {"maps": [], "sets": []}
    wanted = set(buckets or ("new", "improver", "maintain"))

    rankings = {}
    for key, _label, fn in DIMENSIONS:
        values = sorted(v for v in (p["values"].get(key) for p in plays)
                        if v is not None)
        rankings[key] = values

    peak = (comfort + STRETCH_PEAK * stretch) if comfort is not None else None
    sigma = 0.35 + 0.5 * stretch

    scored = []
    counts = {"new": 0, "improver": 0, "maintain": 0, "blocked": 0,
              "gated": 0, "played_other": 0, "relax_only": 0}
    for row in library_rows:
        md5 = row["beatmap_md5"]
        sr = _num(row["sr"])
        set_id = row["set_id"]
        if blacklist.is_blocked(blocked, md5, set_id):
            counts["blocked"] += 1
            continue
        if ((row["length_ms"] or 0) < MIN_LENGTH_MS
                or (row["length_ms"] or 0) > MAX_LENGTH_MS
                or (row["n_objects"] or 0) < MIN_OBJECTS or sr is None):
            counts["gated"] += 1
            continue
        if comfort is not None and abs(sr - comfort) > BAND:
            counts["gated"] += 1
            continue

        attempts = history.get(md5)
        if not attempts and md5 in played_any:
            counts["relax_only"] += 1
            continue
        band = _band(sr)
        band_median = bands.get(band) if band is not None else None
        bucket, detail = _classify(attempts, band_median)
        if bucket is None:
            counts["played_other"] += 1
            continue
        if bucket not in wanted:
            continue
        counts[bucket] += 1

        values = values_by_md5.get(md5) or _dimension_values(row)
        weakness, similarity = _similarity(profile["weaknesses"], values, rankings)
        diff_fit = (math.exp(-0.5 * ((sr - peak) / sigma) ** 2)
                    if peak is not None else 1.0)
        bucket_term = _bucket_term(bucket, detail)
        score = (0.5 + similarity) * diff_fit * bucket_term
        scored.append({
            "beatmap_md5": md5,
            "set_id": set_id,
            "title": row["title"],
            "artist": row["artist"],
            "creator": row["creator"],
            "version": row["version"],
            "sr": round(sr, 3),
            "bpm": round(row["bpm"], 2) if row["bpm"] is not None else None,
            "length_ms": row["length_ms"],
            "bucket": bucket,
            "score": round(score, 6),
            "weakness": weakness,
            "why": _why(row, values, bucket, detail, weakness),
            **detail,
        })

    # interleave the buckets instead of letting one score-scale win outright:
    # the three mean different things to a player, and six improvers in a row is
    # not a plan. Order inside a bucket stays score order.
    scored.sort(key=lambda c: (-c["score"], c["beatmap_md5"]))
    by_bucket = {name: [c for c in scored if c["bucket"] == name]
                 for name in ("new", "improver", "maintain")}
    order = [name for name in ("new", "improver", "maintain")
             if name in wanted and by_bucket[name]]
    picked, seen_sets, turn = [], set(), 0
    limit = max(1, limit)
    while len(picked) < limit and any(by_bucket[name] for name in order):
        name = order[turn % len(order)]
        turn += 1
        while by_bucket[name]:
            cand = by_bucket[name].pop(0)
            key = cand["set_id"]
            if key is not None:
                if key in seen_sets:
                    continue
                seen_sets.add(key)
            picked.append(cand)
            break

    return {
        "player": player,
        "basis": "weakness" if profile["weaknesses"] else "difficulty-only",
        "comfort_sr": comfort,
        "stretch": round(stretch, 3),
        "skills": profile,
        "recommendations": picked,
        "counts": counts,
    }


def _classify(attempts, band_median):
    """``(bucket, detail)`` for one map; ``(None, {})`` when it is not eligible."""
    if not attempts:
        return "new", {"n_attempts": 0, "last_played": None,
                       "best_accuracy": None, "latest_accuracy": None,
                       "band_median_accuracy": _pp(band_median)}
    latest = attempts[-1]
    best = max(p["accuracy"] for p in attempts)
    detail = {
        "n_attempts": len(attempts),
        "last_played": latest["played_at"],
        "best_accuracy": round(100.0 * best, 2),
        "latest_accuracy": round(100.0 * latest["accuracy"], 2),
        "band_median_accuracy": _pp(band_median),
    }
    if band_median is None or len(attempts) < 2:
        return None, {}
    if latest["failed"] or latest["accuracy"] < band_median - IMPROVER_GAP:
        return "improver", detail
    days = _days_since(latest["played_at"])
    if latest["accuracy"] >= band_median and days is not None and days >= MAINTAIN_DAYS:
        detail["days_since"] = round(days)
        return "maintain", detail
    return None, {}


def _pp(value):
    return None if value is None else round(100.0 * value, 2)


def _bucket_term(bucket, detail) -> float:
    if bucket == "improver":
        gap = max(0.0, (detail.get("band_median_accuracy") or 0.0)
                  - (detail.get("latest_accuracy") or 0.0))
        return 1.0 + min(1.0, gap / 10.0)
    if bucket == "maintain":
        return 0.6 + 0.4 * min(1.0, (detail.get("days_since") or 0) / 90.0)
    return 1.0


def _similarity(weaknesses, values, rankings):
    """How strongly this map sits on the bad side of your weaknesses.

    Returns ``(weakness_entry | None, 0..1)``. With no weakness, similarity is
    0 and the caller falls back to difficulty fit alone (``basis`` says so).
    """
    best, best_factor = None, 0.0
    for w in weaknesses:
        value = values.get(w["key"])
        if value is None or not rankings.get(w["key"]):
            continue
        rank = _pct_rank(rankings[w["key"]], value)
        factor = (rank - 0.5) * 2.0 if w["bad_side"] == "high" else (0.5 - rank) * 2.0
        factor = max(0.0, min(1.0, factor)) * w.get("weight", 1.0)
        if factor > best_factor:
            best, best_factor = w, factor
    return best, round(best_factor, 4)


def _why(row, values, bucket, detail, weakness) -> str:
    """One deterministic sentence (the card shows it verbatim)."""
    parts = []
    if row["sr"] is not None:
        parts.append(f"{float(row['sr']):.2f}\u2605")
    if row["bpm"]:
        parts.append(f"{float(row['bpm']):.0f} BPM")
    parts.append(_clock(row["length_ms"]))
    parts.append(_material(values))
    if weakness is not None:
        parts.append(
            f"trains {weakness['label']} — you miss "
            f"{weakness['miss_bad_pct']:.1f}% on that half vs "
            f"{weakness['miss_good_pct']:.1f}% on the other "
            f"(n={weakness['n_bad']}/{weakness['n_good']})")
    else:
        parts.append("difficulty-appropriate")
    if bucket == "new":
        parts.append("never played")
    elif bucket == "improver":
        parts.append(
            f"improver: best {detail['best_accuracy']:.1f}% over "
            f"{detail['n_attempts']} run{'s' if detail['n_attempts'] != 1 else ''}, "
            f"this band's median {detail['band_median_accuracy']:.1f}%, "
            f"last attempt {detail['latest_accuracy']:.1f}%")
    else:
        parts.append(
            f"maintain: {detail['latest_accuracy']:.1f}% here, last played "
            f"{detail['days_since']:.0f}d ago")
    return " \u00b7 ".join(parts)


def render_lines(result: dict) -> list[str]:
    """The CLI text form."""
    if result.get("error"):
        return [f"recommend: {result['error']}"]
    lines = [f"player: {result['player']}   basis: {result['basis']}   "
             f"comfort SR: {result['comfort_sr']}"]
    skills = result.get("skills") or {}
    lines.append(f"evidence: {skills.get('n_runs', 0)} runs "
                 f"({skills.get('window')}, {skills.get('excluded_relax', 0)} "
                 f"relax excluded)")
    for w in skills.get("weaknesses") or []:
        red = f" (same as {w['redundant_with']})" if w.get("redundant_with") else ""
        lines.append(f"  weak  {w['label']:>16}: misses {w['miss_bad_pct']:.1f}% vs "
                     f"{w['miss_good_pct']:.1f}% on the other half "
                     f"(n={w['n_bad']}/{w['n_good']}, +{w['gap_pp']:.1f} pp excess){red}")
    for s in skills.get("strengths") or []:
        lines.append(f"  good  {s['label']:>16}: misses {s['miss_pct']:.1f}% (n={s['n']})")
    if not result["recommendations"]:
        lines.append("no candidates — is the library scanned? "
                     "(`osu-critique library scan`)")
    for i, c in enumerate(result["recommendations"], 1):
        lines.append(f"{i}. [{c['bucket']}] {c['artist']} - {c['title']} "
                     f"[{c['version']}] \u2014 {c['why']}  (score {c['score']:.3f})")
    counts = result.get("counts") or {}
    if counts:
        lines.append("pool: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return lines
