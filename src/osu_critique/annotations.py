"""Human annotations: the player's own notes, which the LLM critic reads.

A note is either **map-scoped** (applies to every attempt at a beatmap) or
**run-scoped** (belongs to one attempt). A note may carry a timestamp; with no
timestamp it is a general comment.

Storage is one canonical JSON sidecar per beatmap —
``out/annotations/<beatmap_md5>.json`` — because annotations are *authored*,
not derived: deleting the SQLite index must never lose one. The index mirrors
them for querying.

Timestamps are stored in **map time** (seconds on the ``.osu``'s own clock),
never in a run's calibrated row clock. A DT replay's rows are in player time
(``rows_scale`` = 2/3), so a note stamped at row 667 ms is map 1.000 s and
renders at 667 ms on that run and 1.000 s on any other attempt at the map.
See ``docs/annotations.md``.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

SIDECAR_VERSION = 1
SCOPES = ("map", "run")
MAX_BODY = 4000


# ----------------------------------------------------------------- helpers --

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def annotations_dir(outdir) -> Path:
    return Path(outdir) / "annotations"


def sidecar_path(outdir, beatmap_md5: str) -> Path:
    return annotations_dir(outdir) / f"{beatmap_md5}.json"


def _empty(beatmap_md5: str) -> dict:
    return {"schema_version": SIDECAR_VERSION, "beatmap_md5": beatmap_md5,
            "notes": []}


def load(outdir, beatmap_md5: str) -> dict:
    """Read one sidecar. Missing or malformed files are an empty set of notes."""
    doc = _empty(beatmap_md5)
    try:
        with open(sidecar_path(outdir, beatmap_md5)) as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return doc
    if not isinstance(raw, dict) or not isinstance(raw.get("notes"), list):
        return doc
    notes = []
    for note in raw["notes"]:
        clean = _validate_note(note, allow_partial=True)
        if clean is not None:
            notes.append(clean)
    doc["notes"] = notes
    return doc


def save(outdir, beatmap_md5: str, doc: dict) -> Path:
    """Atomic write: a crash mid-save must not truncate someone's notes."""
    dest = sidecar_path(outdir, beatmap_md5)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SIDECAR_VERSION, "beatmap_md5": beatmap_md5,
               "notes": doc.get("notes", [])}
    tmp = dest.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False,
                              sort_keys=True) + "\n")
    os.replace(tmp, dest)
    return dest


_TS_RE = re.compile(r"^\s*(?:(\d+):)?(\d+(?:\.\d+)?)\s*$")


def parse_time(value) -> float | None:
    """``"134.312"`` or ``"2:14.312"`` or a number -> seconds (float).

    Accepts a bare number as seconds. Returns None for an empty value.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value).strip()
    if not text:
        return None
    match = _TS_RE.match(text)
    if not match:
        raise ValueError(f"cannot read a timestamp from {value!r} "
                         "(use 134.312 or 2:14.312)")
    minutes = int(match.group(1) or 0)
    seconds = float(match.group(2))
    return max(0.0, minutes * 60 + seconds)


def fmt_time(t_map) -> str:
    """Seconds -> ``m:ss.mmm`` (the chip shown next to a note)."""
    if t_map is None:
        return ""
    total = max(0.0, float(t_map))
    minutes = int(total // 60)
    return f"{minutes}:{total - minutes * 60:06.3f}"


def to_map_time(row_ms, time_base: dict | None) -> float:
    """A row (frame-clock) millisecond -> map-time seconds."""
    scale = float((time_base or {}).get("rows_scale") or 1.0)
    return (float(row_ms) / scale) / 1000.0


def to_row_ms(t_map, time_base: dict | None) -> float:
    """Map-time seconds -> the row clock of a specific run."""
    scale = float((time_base or {}).get("rows_scale") or 1.0)
    return float(t_map) * 1000.0 * scale


# -------------------------------------------------------------- validation --

def _validate_note(note, allow_partial: bool = False) -> dict | None:
    if not isinstance(note, dict):
        return None
    scope = note.get("scope")
    if scope not in SCOPES:
        return None
    body = str(note.get("body") or "").strip()
    if not body:
        return None
    if scope == "run" and not note.get("replay_md5"):
        return None
    note_id = str(note.get("note_id") or "").strip()
    if not note_id:
        if allow_partial:      # tolerate a hand-edited file by minting an id
            note_id = new_id()
        else:
            return None
    tags = note.get("tags") or []
    if isinstance(tags, str):
        tags = [t for t in re.split(r"[,\s]+", tags) if t]
    tags = [str(t).strip() for t in tags if str(t).strip()][:12]
    t_map = note.get("t_map")
    if t_map is not None:
        try:
            t_map = max(0.0, float(t_map))
        except (TypeError, ValueError):
            t_map = None
    return {
        "note_id": note_id,
        "scope": scope,
        "replay_md5": note.get("replay_md5") if scope == "run" else None,
        "t_map": t_map,
        "body": body[:MAX_BODY],
        "tags": tags,
        "created_at": note.get("created_at") or _now(),
        "updated_at": note.get("updated_at"),
    }


def new_id() -> str:
    return secrets.token_hex(4)


# -------------------------------------------------------------------- CRUD --

def add(outdir, beatmap_md5: str, body: str, scope: str = "map",
        replay_md5: str | None = None, t_map=None, tags=None) -> dict:
    """Append one note and return it. Raises ValueError on bad input."""
    if not beatmap_md5:
        raise ValueError("a note needs a beatmap_md5")
    candidate = _validate_note({
        "note_id": new_id(), "scope": scope, "replay_md5": replay_md5,
        "t_map": t_map, "body": body, "tags": tags or [],
        "created_at": _now(), "updated_at": None,
    })
    if candidate is None:
        raise ValueError(
            "a note needs scope='map' or 'run', a non-empty body, and a "
            "replay_md5 when scope='run'")
    doc = load(outdir, beatmap_md5)
    doc["notes"].append(candidate)
    save(outdir, beatmap_md5, doc)
    return candidate


def remove(outdir, beatmap_md5: str, note_id: str) -> bool:
    doc = load(outdir, beatmap_md5)
    kept = [n for n in doc["notes"] if n["note_id"] != note_id]
    if len(kept) == len(doc["notes"]):
        return False
    doc["notes"] = kept
    save(outdir, beatmap_md5, doc)
    return True


def find_owner(outdir, note_id: str) -> str | None:
    """Which beatmap's sidecar holds this note id (for ``annotate rm <id>``)."""
    for path in sorted(annotations_dir(outdir).glob("*.json")):
        doc = load(outdir, path.stem)
        if any(n["note_id"] == note_id for n in doc["notes"]):
            return path.stem
    return None


def all_notes(outdir) -> list[dict]:
    """Every note in every sidecar, each with its ``beatmap_md5``."""
    out = []
    directory = annotations_dir(outdir)
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        for note in load(outdir, path.stem)["notes"]:
            out.append({**note, "beatmap_md5": path.stem})
    return out


def for_map(outdir, beatmap_md5: str, replay_md5: str | None = None) -> dict:
    """``{"map": [...], "run": [...]}`` for one beatmap.

    Run notes are filtered to ``replay_md5`` when one is given; a map page
    (no run) gets every run note so nothing is silently hidden.
    """
    notes = load(outdir, beatmap_md5)["notes"]
    map_notes = [n for n in notes if n["scope"] == "map"]
    run_notes = [n for n in notes if n["scope"] == "run"]
    if replay_md5 is not None:
        run_notes = [n for n in run_notes if n["replay_md5"] == replay_md5]
    for n in map_notes + run_notes:
        n["t_label"] = fmt_time(n["t_map"])
    map_notes.sort(key=lambda n: (n["t_map"] is None, n["t_map"] or 0.0))
    run_notes.sort(key=lambda n: (n["t_map"] is None, n["t_map"] or 0.0))
    return {"map": map_notes, "run": run_notes}


def for_metrics(metrics: dict, outdir) -> list[dict]:
    """The notes that apply to one run's metrics doc (map notes + its own)."""
    md5 = metrics.get("beatmap_md5")
    if not md5:
        return []
    groups = for_map(outdir, md5, metrics.get("replay_md5"))
    return groups["map"] + groups["run"]


# ------------------------------------------------------------------ prompt --

def prompt_block(notes: list[dict], beaten_map: str | None = None) -> str:
    """The section the coach/prompt reads: the player's words, with timestamps."""
    if not notes:
        return ""
    lines = ["## The player's own notes (human annotations)",
             "Written by the player about this map or play — treat them as "
             "context and a hypothesis, not as measured fact. When a timestamp is "
             "given, check the objects near it in the metrics."]
    for note in notes:
        where = "map" if note["scope"] == "map" else "this play"
        stamp = f"{fmt_time(note['t_map'])} — " if note.get("t_map") is not None else ""
        tags = f"  [{', '.join(note['tags'])}]" if note.get("tags") else ""
        lines.append(f"- ({where}) {stamp}{note['body']}{tags}")
    return "\n".join(lines)
