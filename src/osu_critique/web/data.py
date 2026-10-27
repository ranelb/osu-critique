"""View models for the web frontend.

Templates get plain dicts; this module is the only place that knows SQL and the
artifact layout. Nothing here computes analysis: numbers come from the index
(a projection of the artifacts) or straight out of one metrics JSON.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..index import get_beatmap, get_run, runs_for_map

#: Every ordering the list page offers, as (key, SQL, label).
SORTS = {
    "recent": ("last_played DESC", "recent"),
    "accuracy": ("best_acc DESC", "accuracy"),
    "sr": ("sr DESC", "star rating"),
    "attempts": ("attempts DESC", "attempts"),
    "pp": ("best_pp DESC", "pp"),
}


def _fmt_when(iso):
    if not iso:
        return "—"
    return iso[:16].replace("T", " ")


def _row_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def _metrics_at(path):
    """Load one artifact; None when it vanished (the index can be stale)."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _decorate_run(run: dict) -> dict:
    run["when"] = _fmt_when(run.get("played_at"))
    run["acc_pct"] = (run["accuracy"] or 0) * 100 if run.get("accuracy") is not None else None
    run["miss"] = _misses(run.get("counts_recorded_json"))
    return run


def _misses(counts_json):
    try:
        return int((json.loads(counts_json or "{}") or {}).get("miss") or 0)
    except (ValueError, TypeError):
        return 0


# ------------------------------------------------------------------- list ----

def list_maps(conn, q=None, sort="recent", status=None, trust_only=False,
              limit=120, offset=0) -> dict:
    """One card per beatmap, aggregated over its (de-duplicated) attempts."""
    order_sql, order_label = SORTS.get(sort, SORTS["recent"])
    where = ["r.beatmap_md5 <> ''"]
    args = []
    if q:
        needle = f"%{q.strip()}%"
        where.append("(b.title LIKE ? OR b.artist LIKE ? OR b.title_unicode LIKE ? "
                     "OR b.artist_unicode LIKE ? OR r.map_name LIKE ?)")
        args += [needle] * 5
    if status:
        where.append("r.rank_status = ?")
        args.append(status)
    if trust_only:
        where.append("r.trust_ok = 1")

    latest = ("(SELECT r2.rank_status FROM runs r2 WHERE r2.beatmap_md5 = r.beatmap_md5 "
              " ORDER BY r2.played_at DESC, r2.mtime DESC LIMIT 1)")
    sql = f"""
        SELECT r.beatmap_md5 AS md5,
               b.title, b.title_unicode, b.artist, b.artist_unicode, b.version,
               b.creator, b.set_id, b.metadata_missing,
               COUNT(DISTINCT r.run_id) AS attempts,
               MAX(r.accuracy) AS best_acc,
               AVG(r.accuracy) AS avg_acc,
               MAX(r.played_at) AS last_played,
               MAX(r.pp) AS best_pp,
               MAX(r.sr) AS sr,
               {latest} AS rank_status,
               (SELECT MAX(r3.map_name) FROM runs r3
                 WHERE r3.beatmap_md5 = r.beatmap_md5) AS map_name
        FROM runs r LEFT JOIN beatmaps b ON b.beatmap_md5 = r.beatmap_md5
        WHERE {' AND '.join(where)}
        GROUP BY r.beatmap_md5
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """
    rows = [_row_dict(r) for r in conn.execute(sql, (*args, limit, offset))]
    total = conn.execute(
        f"SELECT COUNT(DISTINCT r.beatmap_md5) FROM runs r "
        f"LEFT JOIN beatmaps b ON b.beatmap_md5 = r.beatmap_md5 "
        f"WHERE {' AND '.join(where)}", args).fetchone()[0]
    for row in rows:
        row["title_display"] = _title(row)
        row["acc_pct"] = (row["best_acc"] or 0) * 100 if row["best_acc"] is not None else None
        row["last"] = _fmt_when(row["last_played"])
    return {"maps": rows, "total": total, "limit": limit, "offset": offset,
            "has_next": offset + len(rows) < total,
            "sort": sort if sort in SORTS else "recent", "sort_label": order_label}


def _title(row) -> str:
    """``Artist - Title`` from the .osu metadata, falling back to the metrics."""
    artist = row.get("artist_unicode") or row.get("artist")
    title = row.get("title_unicode") or row.get("title")
    if artist and title:
        return f"{artist} - {title}"
    return row.get("map_name") or "unknown map"


# -------------------------------------------------------------------- map ----

def map_page(conn, md5: str, sort: str = "played_at") -> dict | None:
    bm_row = get_beatmap(conn, md5)
    attempts = [_decorate_run(_row_dict(r))
                for r in runs_for_map(conn, md5, order=sort)]
    if not attempts and bm_row is None:
        return None
    beatmap = _row_dict(bm_row) if bm_row is not None else {
        "beatmap_md5": md5, "title": None, "artist": None, "version": None,
        "creator": None, "set_id": None, "metadata_missing": 1,
        "background": None, "beatmap_id": None, "mode": None, "map_path": None,
    }
    best = max((a for a in attempts if a.get("accuracy") is not None),
               key=lambda a: a["accuracy"], default=None)
    accs = [a["accuracy"] for a in attempts if a.get("accuracy") is not None]
    sr = next((a["sr"] for a in attempts if a.get("sr") is not None), None)
    status = attempts[0]["rank_status"] if attempts else None
    page = {
        "beatmap": beatmap,
        "md5": md5,
        "attempts": attempts,
        "n_attempts": len(attempts),
        "best": best,
        "avg_acc": sum(accs) / len(accs) if accs else None,
        "sr": sr,
        "status": status,
        "untrusted": sum(1 for a in attempts if not a["trust_ok"]),
        "title_display": _title(beatmap),
        "sort": sort if sort in ("played_at", "accuracy", "ur") else "played_at",
        "cross_attempt": None,
        "annotations": [],          # 0.14.0
    }
    if len(attempts) >= 2:
        page["cross_attempt"] = _cross_attempt(attempts)
    return page


def _cross_attempt(attempts: list[dict]) -> dict | None:
    from ..metrics.attempts import build

    rows = []
    for a in attempts:
        metrics = _metrics_at(a["json_path"])
        if metrics is not None:
            rows.append((a["json_path"], metrics))
    if len(rows) < 2:
        return None
    try:
        block = build(rows)
    except Exception:  # a shape change in one artifact must not kill the page
        return None
    mp = next((m for m in block["maps"] if m["n_attempts"] >= 2), None)
    return mp


# -------------------------------------------------------------------- run ----

#: The object table shows the rows worth looking at, not 900 300s.
INTERESTING = ("miss", "100", "50")


def run_page(conn, run_id: str) -> dict | None:
    row = get_run(conn, run_id)
    if row is None:
        return None
    run = _decorate_run(_row_dict(row))
    metrics = _metrics_at(run["json_path"]) or {}
    objects = _objects(run)
    interesting = [o for o in objects if o.get("result") in INTERESTING]
    report_sections = []
    if metrics:
        try:
            from ..report_sections import sections as build_sections
            from ..report_sections import to_text
            report_sections = build_sections(metrics)
        except Exception:
            report_sections = []
    beatmap = _row_dict(get_beatmap(conn, run["beatmap_md5"])) if run["beatmap_md5"] else None
    title = _title(beatmap) if beatmap else None
    if title and beatmap.get("version"):
        title = f"{title} [{beatmap['version']}]"
    from .boards import build as build_boards

    boards = (build_boards(metrics, objects) if objects else
              {"playfield": {"w": 512.0, "h": 384.0}, "misses": [],
               "heat": [], "good": []})
    duration = max((o.get("t") or 0) for o in objects) if objects else 0
    return {
        "run": run,
        "metrics": metrics,
        "beatmap": beatmap,
        "title_display": title or run.get("map_name") or "run",
        "rows_scale": float((metrics.get("time_base") or {}).get("rows_scale") or 1.0),
        "duration_ms": duration,
        "boards": boards,
        "report_sections": report_sections,
        "report_text": (to_text(metrics, report_sections)
                        if report_sections else ""),
        "n_report_sections": sum(1 for sec in report_sections
                                 if any(item.get("tone") != "headline"
                                        for item in sec["items"])),
        "objects": objects,
        "interesting": interesting,
        "n_interesting": len(interesting),
        "n_objects": len(objects),
        "objects_available": bool(objects),
        "trust": run["trust_ok"] == 1,
        "annotations": [],          # 0.14.0
        "critique": None,           # 0.15.0
    }


#: One rail entry per block a reader might want to jump to. The counts are what
#: the block holds, never a metric that is already on the cards above.
def run_toc(page: dict) -> list:
    notes = page.get("notes") or {}
    entries = [{"id": "stats", "label": "summary"},
               {"id": "chart", "label": "chart"}]
    if page.get("boards", {}).get("misses"):
        entries.append({"id": "boards", "label": "boards",
                        "count": len(page["boards"]["misses"])})
    if page.get("objects_available"):
        entries.append({"id": "objects", "label": "objects",
                        "count": page.get("n_interesting") or 0})
    if page.get("n_report_sections"):
        entries.append({"id": "report", "label": "report",
                        "count": page["n_report_sections"]})
    entries.append({"id": "critique", "label": "llm"})
    n_notes = len(notes.get("map") or []) + len(notes.get("run") or [])
    entries.append({"id": "annotations", "label": "notes", "count": n_notes})
    return entries


def map_toc(page: dict) -> list:
    notes = page.get("notes") or {}
    entries = [{"id": "attempts", "label": "attempts",
                "count": page.get("n_attempts") or 0}]
    if page.get("cross_attempt"):
        entries.append({"id": "cross", "label": "cross-attempt"})
    entries.append({"id": "annotations", "label": "notes",
                    "count": len(notes.get("map") or [])})
    return entries


def report_text(run_row: dict) -> str | None:
    """The deterministic report as the CLI prints it, for the copy button."""
    metrics = _metrics_at(run_row.get("json_path") or "") or {}
    if not metrics:
        return None
    from ..report_sections import sections, to_text
    return to_text(metrics, sections(metrics))


def _objects(run: dict) -> list:
    path = run.get("objects_path")
    if not path or not Path(path).is_file():
        return []
    try:
        with open(path) as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return []
    rows = doc.get("objects") if isinstance(doc, dict) else doc
    return rows if isinstance(rows, list) else []
