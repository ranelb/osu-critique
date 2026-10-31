"""Per-map / per-set blacklist: "never recommend this again".

Authored data, so it lives in a sidecar — ``out/blacklist.json`` — and the index
mirrors it, exactly like annotations and stored critiques. Deleting
``out/index.sqlite`` must never un-blacklist a map.

Two scopes:

``maps``
    a beatmap md5: one difficulty.
``sets``
    a ``BeatmapSetID``: every difficulty of that beatmapset, including ones
    imported later.

The score is per-map, so a set entry is applied at match time by looking at the
candidate's ``set_id``; nothing has to be expanded into md5s first.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

SIDECAR_VERSION = 1
SCOPES = ("map", "set")


def path(outdir) -> Path:
    return Path(outdir) / "blacklist.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty() -> dict:
    return {"schema_version": SIDECAR_VERSION, "maps": [], "sets": [],
            "updated": None}


def load(outdir) -> dict:
    """The sidecar, normalised. A missing or malformed file means "nothing blocked"."""
    doc = _empty()
    try:
        raw = json.loads(path(outdir).read_text())
    except (OSError, ValueError):
        return doc
    if not isinstance(raw, dict):
        return doc

    def clean(values, cast):
        out = []
        for v in values if isinstance(values, list) else []:
            try:
                item = cast(v)
            except (TypeError, ValueError):
                continue
            if item and item not in out:
                out.append(item)
        return out

    doc["maps"] = clean(raw.get("maps"), str)
    doc["sets"] = clean(raw.get("sets"), int)
    doc["updated"] = raw.get("updated")
    return doc


def save(outdir, doc: dict) -> Path:
    """Write the sidecar atomically (a half-written blacklist is worse than none)."""
    target = path(outdir)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = {**_empty(), **{k: doc.get(k) for k in ("maps", "sets")},
           "updated": doc.get("updated") or _now()}
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    os.replace(tmp, target)
    return target


def _mutate(outdir, fn) -> dict:
    doc = load(outdir)
    fn(doc)
    doc["updated"] = _now()
    save(outdir, doc)
    return doc


def add_map(outdir, beatmap_md5: str) -> dict:
    return _mutate(outdir, lambda d: d["maps"].append(beatmap_md5)
                   if beatmap_md5 not in d["maps"] else None)


def remove_map(outdir, beatmap_md5: str) -> dict:
    return _mutate(outdir, lambda d: d.__setitem__(
        "maps", [m for m in d["maps"] if m != beatmap_md5]))


def add_set(outdir, set_id: int) -> dict:
    set_id = int(set_id)
    return _mutate(outdir, lambda d: d["sets"].append(set_id)
                   if set_id not in d["sets"] else None)


def remove_set(outdir, set_id: int) -> dict:
    set_id = int(set_id)
    return _mutate(outdir, lambda d: d.__setitem__(
        "sets", [s for s in d["sets"] if s != set_id]))


def is_blocked(doc: dict, beatmap_md5: str | None, set_id=None) -> bool:
    if beatmap_md5 and beatmap_md5 in doc.get("maps", ()):
        return True
    if set_id is not None and int(set_id) in doc.get("sets", ()):
        return True
    return False


# --------------------------------------------------------------- the mirror --

def rows(outdir) -> list[tuple[str, str, str]]:
    """``[(key, scope, created_at)]`` — the index's flat shape."""
    doc = load(outdir)
    stamp = doc.get("updated") or _now()
    out = [(md5, "map", stamp) for md5 in doc["maps"]]
    out += [(f"set:{sid}", "set", stamp) for sid in doc["sets"]]
    return out


def mirror(conn, outdir) -> int:
    """Replace the ``blacklist`` mirror from the canonical sidecar."""
    entries = rows(outdir)
    conn.execute("DELETE FROM blacklist")
    for key, scope, created in entries:
        conn.execute(
            "INSERT OR REPLACE INTO blacklist (key, scope, created_at, source_path) "
            "VALUES (?, ?, ?, ?)", (key, scope, created, str(path(outdir))))
    conn.commit()
    return len(entries)
