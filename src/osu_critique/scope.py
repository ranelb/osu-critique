"""A selection of runs -> the deterministic summary the model reads.

The critique tab composes a *scope*: individual replays, whole maps (every
attempt), and date ranges, added together. This module resolves that scope
against the index and renders the one text the page shows and the model gets.
There is no second prompt path: if the text does not say it, the model does not
know it.

Sizing, because a selection is unbounded:

- up to ``FULL_REPORT_LIMIT`` runs get their full per-replay report appended;
- above that the selection is summarised — overview, per-map table (top
  ``MAP_TABLE_LIMIT`` maps by play count), per-run table (most recent
  ``RUN_TABLE_LIMIT``), and the cross-attempt stability block for maps played
  more than once;
- everything omitted is counted in the header, so both the reader and the model
  know what the summary is not.

The output is deterministic for a given selection and corpus: no timestamps of
"now", stable sorting, notes in file order. The stored-critique hash covers the
text, so a rebuild that differs is a different artifact by definition.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

FULL_REPORT_LIMIT = 10       # above this, per-replay reports are dropped
MAP_TABLE_LIMIT = 40         # maps in the table, by play count
RUN_TABLE_LIMIT = 120        # rows in the per-run table, most recent first
MAX_TEXT_BYTES = 300_000     # refuse to generate above this

PRESETS = ("today", "session", "7d", "30d")
SESSION_GAP_HOURS = 3        # a longer silence starts a new session


def empty_selection() -> dict:
    return {"runs": [], "maps": [], "since": None, "until": None}


def from_query(query) -> dict:
    """``{"runs": "a,b", "maps": "md5,md5", "since": ..., "until": ...}`` -> selection.

    Tolerant on purpose: a hand-edited or truncated URL should degrade to a
    smaller selection, never to a 500.
    """
    def ids(key):
        raw = (query.get(key) or "") if hasattr(query, "get") else ""
        if isinstance(raw, list):
            raw = ",".join(raw)
        seen, out = set(), []
        for part in str(raw).split(","):
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                out.append(part)
        return out

    def stamp(key):
        raw = (query.get(key) or "").strip() if hasattr(query, "get") else ""
        return raw or None

    return {"runs": ids("runs"), "maps": ids("maps"),
            "since": stamp("since"), "until": stamp("until")}


# ------------------------------------------------------------------ window --

def window(since: str | None, until: str | None,
           now: datetime | None = None) -> tuple[str | None, str | None]:
    """Resolve a preset or date into ``(from, to_exclusive)`` ISO strings.

    Ranges read ``played_at`` — when the play happened — never when it was
    exported or analysed. ``until`` is inclusive of the whole day.
    """
    now = now or datetime.now()
    start = None
    if since:
        if since in ("today",):
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif since in ("7d", "30d"):
            start = now - timedelta(days=int(since[:-1]))
        else:
            try:
                start = datetime.fromisoformat(since).replace(
                    hour=0, minute=0, second=0, microsecond=0)
            except ValueError:
                start = None
    end = None
    if until:
        try:
            end = datetime.fromisoformat(until).replace(
                hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        except ValueError:
            end = None
    return (start.isoformat(timespec="seconds") if start else None,
            end.isoformat(timespec="seconds") if end else None)


def session_start(conn, now: datetime | None = None) -> str | None:
    """Start of the play session in progress: the last gap longer than 3 hours."""
    rows = conn.execute(
        "SELECT played_at FROM runs WHERE played_at IS NOT NULL "
        "ORDER BY played_at DESC").fetchall()
    previous = None
    for row in rows:
        stamp = row[0]
        try:
            current = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            continue
        if previous is not None and (previous - current) >= timedelta(
                hours=SESSION_GAP_HOURS):
            return previous.isoformat(timespec="seconds")
        previous = current
    return rows[-1][0] if rows else None


# ----------------------------------------------------------------- resolve --

_RUN_COLUMNS = ("run_id, json_path, tag, beatmap_md5, map_name, played_at, "
                "mod_string, accuracy, ur, n_objects, n_objects_map, max_combo, "
                "full_combo, counts_recorded_json, trust_ok, failed, is_relax, "
                "whiffed_presses, hit_error_mean, hit_error_std, sr, pp, "
                "rank_status, replay_md5")


def resolve(conn, selection: dict, now: datetime | None = None) -> list[dict]:
    """The runs a selection covers, deduplicated by run_id, oldest first."""
    found: dict[str, dict] = {}

    def add(where: str, args: tuple):
        sql = f"SELECT {_RUN_COLUMNS} FROM runs WHERE {where}"
        for row in conn.execute(sql, args):
            doc = dict(row)
            found.setdefault(doc["run_id"], doc)

    if selection.get("runs"):
        marks = ",".join("?" * len(selection["runs"]))
        add(f"run_id IN ({marks})", tuple(selection["runs"]))
    if selection.get("maps"):
        marks = ",".join("?" * len(selection["maps"]))
        add(f"beatmap_md5 IN ({marks})", tuple(selection["maps"]))

    since, until = selection.get("since"), selection.get("until")
    if since == "session":
        since = session_start(conn, now)
    since, until = window(since, until, now)
    clauses, args = [], []
    if since:
        clauses.append("played_at >= ?")
        args.append(since)
    if until:
        clauses.append("played_at < ?")
        args.append(until)
    if clauses:
        add(" AND ".join(clauses), tuple(args))

    return sorted(found.values(),
                  key=lambda r: (r.get("played_at") or "", r["run_id"]))


# ------------------------------------------------------------------ render --

def _fmt(value, digits=1, suffix=""):
    if value is None:
        return "—"
    return f"{value:.{digits}f}{suffix}"


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def _map_label(row: dict) -> str:
    name = row.get("map_name") or row.get("beatmap_md5") or "?"
    return name[:64]


_PRESET_LABEL = {"today": "today", "session": "this session",
                 "7d": "the last 7 days", "30d": "the last 30 days"}


def _selector_line(selection: dict) -> str:
    parts = []
    if selection.get("runs"):
        parts.append(f"{len(selection['runs'])} chosen replay(s)")
    if selection.get("maps"):
        parts.append(f"{len(selection['maps'])} map(s), every attempt")
    since, until = selection.get("since"), selection.get("until")
    if since in _PRESET_LABEL:
        parts.append(_PRESET_LABEL[since])
    elif since and until:
        parts.append(f"range {since} → {until}")
    elif since:
        parts.append(f"everything since {since}")
    elif until:
        parts.append(f"everything up to {until}")
    return "; ".join(parts) or "nothing"


def _overview(rows: list[dict]) -> list[str]:
    accs = [r["accuracy"] for r in rows if r.get("accuracy") is not None]
    urs = [r["ur"] for r in rows if r.get("ur") is not None]
    errs = [r["hit_error_mean"] for r in rows if r.get("hit_error_mean") is not None]
    stds = [r["hit_error_std"] for r in rows if r.get("hit_error_std") is not None]
    repeats = sum(1 for r in rows if r.get("full_combo"))
    untrusted = sum(1 for r in rows if r.get("trust_ok") == 0)
    failed = sum(1 for r in rows if r.get("failed"))
    median_acc = _median(accs)
    misses = [_misses(r) for r in rows]
    return [
        f"- accuracy: median {_fmt(median_acc * 100 if median_acc is not None else None, 1, '%')}"
        f", best {_fmt(max(accs) * 100 if accs else None, 1, '%')}"
        f", worst {_fmt(min(accs) * 100 if accs else None, 1, '%')}",
        f"- UR: median {_fmt(_median(urs), 0)}"
        f", best {_fmt(min(urs) if urs else None, 0)}"
        f", worst {_fmt(max(urs) if urs else None, 0)}",
        f"- {sum(misses)} miss(es) in total, median {_fmt(_median(misses), 0)} per run",
        f"- timing: median mean error {_fmt(_median(errs), 1, ' ms')}, "
        f"median σ {_fmt(_median(stds), 1, ' ms')}",
        f"- {repeats} full combo(s), {untrusted} untrusted (judgement mismatch), "
        f"{failed} failed play(s)",
    ]


def _misses(row: dict) -> int:
    import json

    try:
        counts = json.loads(row.get("counts_recorded_json") or "{}")
    except ValueError:
        return 0
    return int(counts.get("miss") or 0)


def _map_table(rows: list[dict]) -> tuple[list[str], int]:
    by_map: dict[str, list[dict]] = {}
    for row in rows:
        by_map.setdefault(row.get("beatmap_md5") or "", []).append(row)
    ordered = sorted(by_map.items(), key=lambda kv: (-len(kv[1]),
                                                     _map_label(kv[1][0])))
    shown, omitted = ordered[:MAP_TABLE_LIMIT], len(ordered) - MAP_TABLE_LIMIT
    lines = ["| map | plays | best acc | median acc | miss | UR median |",
             "|---|---|---|---|---|---|"]
    for _md5, group in shown:
        accs = [r["accuracy"] for r in group if r.get("accuracy") is not None]
        urs = [r["ur"] for r in group if r.get("ur") is not None]
        lines.append(
            f"| {_map_label(group[0])} | {len(group)} "
            f"| {_fmt(max(accs) * 100 if accs else None, 1, '%')} "
            f"| {_fmt(_median(accs) and _median(accs) * 100, 1, '%')} "
            f"| {sum(_misses(r) for r in group)} | {_fmt(_median(urs), 0)} |")
    return lines, omitted


def _run_table(rows: list[dict]) -> tuple[list[str], int]:
    shown = list(reversed(rows))[:RUN_TABLE_LIMIT]
    lines = ["| when | map | mods | acc | UR | miss | whiffs | flag |",
             "|---|---|---|---|---|---|---|---|"]
    for r in shown:
        flags = []
        if r.get("trust_ok") == 0:
            flags.append("untrusted")
        if r.get("failed"):
            flags.append("failed")
        if r.get("is_relax"):
            flags.append("relax")
        lines.append(
            f"| {(r.get('played_at') or '?')[:16].replace('T', ' ')} "
            f"| {_map_label(r)} | {r.get('mod_string') or 'NM'} "
            f"| {_fmt((r.get('accuracy') or 0) * 100, 1, '%')} "
            f"| {_fmt(r.get('ur'), 0)} | {_misses(r)} "
            f"| {r.get('whiffed_presses') or 0} | {' '.join(flags) or '—'} |")
    return lines, max(0, len(rows) - RUN_TABLE_LIMIT)


def _notes_section(outdir, rows: list[dict]) -> str:
    """The player's own words for the selected maps and plays, grouped and sorted."""
    from . import annotations

    seen_maps: dict[str, str] = {}
    blocks: list[str] = []
    for row in rows:
        md5 = row.get("beatmap_md5")
        if not md5 or md5 in seen_maps:
            continue
        seen_maps[md5] = _map_label(row)
        found = annotations.for_map(outdir, md5, row.get("replay_md5"))
        lines = []
        for note in found["map"] + found["run"]:
            where = "map" if note["scope"] == "map" else "run"
            stamp = (f"{note['t_label']} — " if note.get("t_map") is not None else "")
            tags = f"  [{', '.join(note.get('tags') or [])}]" if note.get("tags") else ""
            lines.append(f"- ({where}) {stamp}{note['body']}{tags}")
        if lines:
            blocks.append(f"### {seen_maps[md5]}\n" + "\n".join(lines))
    if not blocks:
        return ""
    head = ("## The player's own notes\n"
            "Written by the player about these maps and plays — context and a "
            "hypothesis, not measured fact.")
    return head + "\n\n" + "\n\n".join(blocks)


def _stability_block(rows: list[dict], metrics: dict[str, dict]) -> str:
    from .metrics import attempts

    pairs = [(r.get("tag") or r["run_id"], metrics[r["run_id"]])
             for r in rows if r["run_id"] in metrics]
    if len(pairs) < 2:
        return ""
    try:
        block = attempts.build(pairs)
    except Exception:
        return ""
    if not block["n_repeated"]:
        return ""
    lines = attempts.describe(block)
    return ("## Stability across attempts (maps played more than once)\n"
            "Rates are per family and per shape class; a rate is only compared "
            "where the bucket is solid enough. \"consistent weakness\" means "
            "worse than the play's own rate in every attempt; \"swings\" is one-off "
            "noise until explained.\n\n" + "\n".join(lines))


def _per_run_reports(rows: list[dict], metrics: dict[str, dict]) -> str:
    from .report_sections import sections, to_text

    blocks = []
    for row in rows:
        doc = metrics.get(row["run_id"])
        if not doc:
            continue
        title = (f"## {_map_label(row)} — "
                 f"{(row.get('played_at') or '?')[:16].replace('T', ' ')} "
                 f"({row.get('mod_string') or 'NM'})")
        try:
            body = to_text(doc, sections(doc))
        except Exception:
            continue
        blocks.append(title + "\n\n" + body)
    return "\n\n".join(blocks)


def render(rows: list[dict], metrics: dict[str, dict], selection: dict,
           outdir) -> str:
    """The whole deterministic text for a resolved selection."""
    parts: list[str] = ["# Critique selection", ""]

    span = (f"{(rows[0].get('played_at') or '?')[:16].replace('T', ' ')} → "
            f"{(rows[-1].get('played_at') or '?')[:16].replace('T', ' ')}"
            if rows else "—")
    n_maps = len({r.get("beatmap_md5") for r in rows})
    header = [f"- {len(rows)} run{'' if len(rows) == 1 else 's'} over "
              f"{n_maps} map{'' if n_maps == 1 else 's'}",
              f"- played {span}",
              f"- selected by: {_selector_line(selection)}"]
    omitted: list[str] = []
    if len(rows) > FULL_REPORT_LIMIT:
        omitted.append(f"per-replay reports (the selection is above "
                       f"{FULL_REPORT_LIMIT} runs)")
    missing = [r for r in rows if r["run_id"] not in metrics]
    if missing:
        omitted.append(f"{len(missing)} run(s) whose metrics artifact is missing")
    parts.append("## What this is\n" + "\n".join(header + [
        ("- omitted: " + "; ".join(omitted)) if omitted else
        "- nothing was omitted: every selected run is shown below"]))
    parts.append("")

    if not rows:
        parts.append("## Nothing matched\nNo runs match this selection.")
        return "\n".join(parts)

    parts.append("## Overview\n" + "\n".join(_overview(rows)))
    parts.append("")

    table, map_omitted = _map_table(rows)
    cap = (f"\n{map_omitted} further maps with fewer plays are not listed."
           if map_omitted else "")
    parts.append("## Maps, busiest first\n" + "\n".join(table) + cap)
    parts.append("")

    table, run_omitted = _run_table(rows)
    cap = (f"\n{run_omitted} older runs are not listed (the per-map table above "
           f"counts them)." if run_omitted else "")
    parts.append("## Runs, newest first\n" + "\n".join(table) + cap)
    parts.append("")

    stability = _stability_block(rows, metrics)
    if stability:
        parts.append(stability)
        parts.append("")

    notes = _notes_section(outdir, rows)
    if notes:
        parts.append(notes)
        parts.append("")

    if len(rows) <= FULL_REPORT_LIMIT:
        reports = _per_run_reports(rows, metrics)
        if reports:
            parts.append("## Per-replay reports\n" + reports)

    return "\n".join(parts).rstrip() + "\n"


# ------------------------------------------------------------------- hash ---

def hash_of(text: str, system: str) -> str:
    blob = (text + "\x00" + system).encode()
    return hashlib.sha256(blob).hexdigest()


def build(conn, outdir, selection: dict, system: str = "",
          now: datetime | None = None) -> dict:
    """Resolve, render and size a selection. No network, no keys, no writes."""
    rows = resolve(conn, selection, now=now)
    metrics: dict[str, dict] = {}
    for row in rows:
        doc = _metrics_at(row.get("json_path"))
        if doc:
            metrics[row["run_id"]] = doc
    text = render(rows, metrics, selection, outdir)
    size = len(text.encode("utf-8"))
    return {
        "selection": selection,
        "rows": rows,
        "text": text,
        "bytes": size,
        "refused": size > MAX_TEXT_BYTES,
        "hash": hash_of(text, system),
        "n_runs": len(rows),
        "n_maps": len({r.get("beatmap_md5") for r in rows}),
        "first": rows[0].get("played_at") if rows else None,
        "last": rows[-1].get("played_at") if rows else None,
        "n_metrics": len(metrics),
    }


def _metrics_at(path) -> dict | None:
    import json
    from pathlib import Path

    if not path:
        return None
    target = Path(path)
    if not target.is_file():
        return None
    try:
        with open(target) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None
