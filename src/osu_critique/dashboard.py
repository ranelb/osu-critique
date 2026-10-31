"""The dashboard: what the home page shows, and the settings that decide it.

Two halves, both plain data:

- :data:`WIDGETS` — the catalogue. Every block on the page is one entry: it can
  be switched off, moved, and (where a window means something) given a window.
- :func:`build` — turns the index into the numbers each widget renders. No
  templating here, no FastAPI: the web layer renders, this decides.

Settings live in ``~/.config/osu-critique/dashboard.json`` (0600, next to
``config.json``), not in ``out/``: they are a preference, not analysis, and
deleting the derived output folder must not reset the page. Unknown widget ids
are ignored and missing ones take their default, so an old or hand-edited file
never blanks the dashboard.
"""
from __future__ import annotations

import json
import os
import statistics as st
from datetime import date, datetime, timedelta

from . import config, digest, recommend

SETTINGS_VERSION = 1

#: Every widget, in default order. ``windows`` are the choices a widget accepts
#: (days for the calendar, weeks for the trend, rows for the recent list); an
#: empty list means the widget has no window knob.
WIDGETS = (
    {"id": "form", "label": "form", "windows": (), "window": None},
    {"id": "recommend", "label": "recommendations", "windows": (), "window": None},
    {"id": "skills", "label": "skill profile", "windows": (), "window": None},
    {"id": "weakspots", "label": "weak spots", "windows": (), "window": None},
    {"id": "trend", "label": "accuracy & UR", "windows": (13, 26), "window": 26},
    {"id": "calendar", "label": "activity", "windows": (91, 182), "window": 182},
    {"id": "recent", "label": "recently played", "windows": (10, 20), "window": 10},
    {"id": "whatsnew", "label": "what's new", "windows": (), "window": None},
)
WIDGET_IDS = tuple(w["id"] for w in WIDGETS)
_BY_ID = {w["id"]: w for w in WIDGETS}

STRETCH_CHOICES = (0.0, 0.25, 0.5, 0.75, 1.0)
CARD_CHOICES = (3, 6, 9)
BUCKETS = ("new", "improver", "maintain")

FORM_WINDOWS = (30, 90)


def settings_path():
    return config.CONFIG_DIR / "dashboard.json"


def defaults() -> dict:
    return {
        "schema_version": SETTINGS_VERSION,
        "player": "",                     # "" = the most-run player in the corpus
        "stretch": 0.5,
        "cards": 6,
        "buckets": list(BUCKETS),
        "widgets": [{"id": w["id"], "on": True, "window": w["window"]}
                    for w in WIDGETS],
    }


# ---------------------------------------------------------------- settings --

def _clean_widgets(raw) -> list[dict]:
    """Known ids only, each once, in the stored order; missing ones defaulted."""
    out, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        wid = item.get("id")
        if wid not in _BY_ID or wid in seen:
            continue
        seen.add(wid)
        allowed = _BY_ID[wid]["windows"]
        window = item.get("window")
        if allowed and window not in allowed:
            window = _BY_ID[wid]["window"]
        out.append({"id": wid, "on": bool(item.get("on", True)),
                    "window": window if allowed else None})
    for w in WIDGETS:                      # old file / hand edit: never blanks
        if w["id"] not in seen:
            out.append({"id": w["id"], "on": True, "window": w["window"]})
    return out


def normalise(raw) -> dict:
    """A stored dict -> the shape the rest of the code relies on."""
    base = defaults()
    if not isinstance(raw, dict):
        return base
    base["player"] = str(raw.get("player") or "").strip()
    try:
        stretch = float(raw.get("stretch", base["stretch"]))
    except (TypeError, ValueError):
        stretch = base["stretch"]
    base["stretch"] = min(STRETCH_CHOICES, key=lambda c: abs(c - stretch))
    try:
        cards = int(raw.get("cards", base["cards"]))
    except (TypeError, ValueError):
        cards = base["cards"]
    base["cards"] = cards if cards in CARD_CHOICES else base["cards"]
    picked = [b for b in (raw.get("buckets") or []) if b in BUCKETS]
    base["buckets"] = picked or list(BUCKETS)
    base["widgets"] = _clean_widgets(raw.get("widgets"))
    return base


def load() -> dict:
    """Read the settings file; anything unreadable means "defaults"."""
    try:
        raw = json.loads(settings_path().read_text())
    except (OSError, ValueError):
        return defaults()
    return normalise(raw)


def save(settings: dict) -> dict:
    """Write the settings atomically (0600: it holds a player name, nothing more)."""
    doc = normalise(settings)
    doc["schema_version"] = SETTINGS_VERSION
    target = settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    os.replace(tmp, target)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return doc


def enabled(settings: dict) -> list[dict]:
    """The switched-on widgets, in order."""
    return [w for w in settings["widgets"] if w["on"]]


# ------------------------------------------------------------------- data --

def _parse(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _mean(values):
    return float(st.fmean(values)) if values else None


def _median(values):
    return float(st.median(values)) if values else None


def player_for(conn, settings: dict) -> str | None:
    """The pinned player, unless the corpus does not have them — then the top one."""
    pinned = settings.get("player")
    if pinned:
        row = conn.execute("SELECT 1 FROM runs WHERE player = ? LIMIT 1",
                           (pinned,)).fetchone()
        if row is not None:
            return pinned
    return recommend.default_player(conn)


def _play_rows(conn, player, since: str | None = None, limit: int | None = None):
    sql = ("SELECT run_id, beatmap_md5, map_name, played_at, accuracy, ur, pp, "
           "mod_string, is_relax FROM runs WHERE player = ? "
           "AND accuracy IS NOT NULL")
    args: list = [player]
    if since:
        sql += " AND played_at >= ?"
        args.append(since)
    sql += " ORDER BY played_at DESC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, args).fetchall()


def _cutoff(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).isoformat()


def form(conn, player) -> dict:
    """Plays, accuracy, UR and pp for the two macro windows."""
    out = {}
    for days in FORM_WINDOWS:
        rows = _play_rows(conn, player, since=_cutoff(days))
        accs = [r["accuracy"] for r in rows]
        urs = [r["ur"] for r in rows if r["ur"] is not None]
        pp = sum(r["pp"] for r in rows if r["pp"] is not None)
        out[str(days)] = {
            "days": days,
            "plays": len(rows),
            "accuracy": round(100.0 * _mean(accs), 2) if accs else None,
            "ur": round(_median(urs), 1) if urs else None,
            "pp": round(pp, 1) if pp else None,
            "maps": len({r["beatmap_md5"] for r in rows}),
        }
    return out


def trend(conn, player, weeks: int) -> dict:
    """Mean accuracy per calendar week (Mon-start) and the median UR of that week."""
    cutoff = _cutoff(weeks * 7 + 7)
    buckets: dict[str, list] = {}
    for row in _play_rows(conn, player, since=cutoff):
        when = _parse(row["played_at"])
        if when is None:
            continue
        start = (when - timedelta(days=when.weekday())).date().isoformat()
        buckets.setdefault(start, []).append(row)
    points = []
    for start in sorted(buckets):
        rows = buckets[start]
        accs = [r["accuracy"] for r in rows]
        urs = [r["ur"] for r in rows if r["ur"] is not None]
        points.append({
            "week": start,
            "plays": len(rows),
            "accuracy": round(100.0 * _mean(accs), 2) if accs else None,
            "ur": round(_median(urs), 1) if urs else None,
        })
    points = points[-weeks:]
    # precompute the plot: a template should not be doing arithmetic on axes
    accs = [p["accuracy"] for p in points if p["accuracy"] is not None]
    lo, hi = (min(accs), max(accs)) if accs else (0.0, 1.0)
    span = max(hi - lo, 2.0)                       # a flat week is not a dramatic one
    n = len(points)
    for i, pnt in enumerate(points):
        pnt["x"] = round(100.0 * i / (n - 1), 2) if n > 1 else 50.0
        acc = pnt["accuracy"] if pnt["accuracy"] is not None else lo
        pnt["y"] = round(100.0 * (hi - acc) / span, 2)
    return {"weeks": weeks, "points": points, "lo": round(lo, 1), "hi": round(hi, 1),
            "best": max(points, key=lambda p: p["accuracy"] or 0) if points else None}


def calendar(conn, player, days: int) -> dict:
    """A per-day play count grid, Monday-first, ending today."""
    today = date.today()
    start = today - timedelta(days=days - 1)
    start -= timedelta(days=start.weekday())          # snap back to a Monday
    counts: dict[str, int] = {}
    for row in conn.execute(
            "SELECT substr(played_at, 1, 10) AS day, COUNT(*) AS n FROM runs "
            "WHERE player = ? AND played_at >= ? GROUP BY day",
            (player, start.isoformat())):
        counts[row["day"]] = row["n"]
    top = max(counts.values(), default=0)
    weeks, week = [], []
    cursor = start
    while cursor <= today:
        n = counts.get(cursor.isoformat(), 0)
        level = 0 if not n else max(1, min(4, round(4 * n / top)))
        week.append({"date": cursor.isoformat(), "n": n, "level": level,
                     "future": cursor > today})
        if len(week) == 7:
            weeks.append(week)
            week = []
        cursor += timedelta(days=1)
    if week:
        weeks.append(week)
    total = sum(counts.values())
    active = sum(1 for n in counts.values() if n)
    return {"weeks": weeks, "total": total, "active_days": active,
            "max": top, "start": start.isoformat(), "end": today.isoformat(),
            "avg_per_active": round(total / active, 1) if active else None}


def recent(conn, player, limit: int) -> list[dict]:
    rows = _play_rows(conn, player, limit=limit)
    return [{
        "run_id": r["run_id"], "beatmap_md5": r["beatmap_md5"],
        "map": r["map_name"], "played_at": r["played_at"],
        "accuracy": r["accuracy"], "mods": r["mod_string"] or "NM",
        "ur": r["ur"], "relax": bool(r["is_relax"]),
    } for r in rows]


def whatsnew(conn, outdir, player) -> dict:
    """The newest digest, plus how many plays it has not seen."""
    items = digest.load_digests(outdir)
    marker, _epoch = digest.last_digest(outdir)
    n_new = 0
    if player:
        sql = "SELECT COUNT(*) FROM runs WHERE player = ?"
        args = [player]
        if marker:
            sql += " AND played_at > ?"
            args.append(marker)
        n_new = conn.execute(sql, args).fetchone()[0]
    latest = items[0] if items else None
    return {
        "digest": latest,
        "n_digests": len(items),
        "n_new": n_new,
        "marker": marker,
        "library": library_state(conn),
    }


def library_state(conn) -> dict:
    """Whether the map library was ever scanned — the recommender's fuel."""
    from . import library

    summary = library.summary(conn)
    if summary is None:
        return {"scanned": False, "maps": 0, "age_days": None}
    when = _parse(summary.get("scanned_at"))
    age = (datetime.now() - when).total_seconds() / 86400.0 if when else None
    return {"scanned": True, "maps": summary.get("maps", 0),
            "age_days": round(age, 1) if age is not None else None,
            "scanned_at": summary.get("scanned_at"),
            "no_sr": summary.get("no_sr", 0)}


def build(conn, outdir, settings: dict) -> dict:
    """The whole page context: resolved settings, player, and per-widget data."""
    player = player_for(conn, settings)
    if player is None:
        return {"player": None, "widgets": enabled(settings), "data": {},
                "library": library_state(conn)}
    on = {w["id"] for w in enabled(settings)}
    windows = {w["id"]: w["window"] for w in settings["widgets"]}
    data: dict = {}

    if "form" in on:
        data["form"] = form(conn, player)
    if "trend" in on:
        data["trend"] = trend(conn, player, windows.get("trend") or 26)
    if "calendar" in on:
        data["calendar"] = calendar(conn, player, windows.get("calendar") or 182)
    if "recent" in on:
        data["recent"] = recent(conn, player, windows.get("recent") or 10)
    if "whatsnew" in on:
        data["whatsnew"] = whatsnew(conn, outdir, player)

    # the recommender produces the profile and the cards in one pass; only pay
    # for it when a widget actually shows either half of it
    if on & {"skills", "weakspots", "recommend"}:
        result = recommend.build(
            outdir, player=player, limit=settings["cards"],
            stretch=settings["stretch"], buckets=settings["buckets"], conn=conn)
        data["skills"] = result.get("skills") or {}
        data["recommend"] = result
    return {"player": player, "widgets": enabled(settings), "data": data,
            "library": data.get("whatsnew", {}).get("library")
            or library_state(conn), "settings": settings}


def toc(page: dict) -> list[dict]:
    """Rail entries: one per enabled widget, with a count where it has one."""
    data = page.get("data") or {}
    out = []
    for widget in page.get("widgets") or []:
        wid = widget["id"]
        count = None
        if wid == "recommend":
            count = len((data.get("recommend") or {}).get("recommendations") or [])
        elif wid == "skills":
            count = len((data.get("skills") or {}).get("weaknesses") or [])
        elif wid == "recent":
            count = len(data.get("recent") or [])
        elif wid == "calendar":
            count = (data.get("calendar") or {}).get("total")
        out.append({"id": f"w-{wid}", "label": _BY_ID[wid]["label"], "count": count})
    return out
