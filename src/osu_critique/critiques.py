"""Stored LLM critiques — one canonical file per run.

A critique is authored data: it cost a call, it is what the model said about
*that* play, and it must survive the index being deleted. So it lives in
``out/critiques/<run_id>.json`` and the DB mirrors it.

Every critique records what it was made from:

- ``run_hash`` — the metrics document **plus the player's annotations**, so
  adding a note (or re-analysing the replay) marks it stale;
- ``prompt_hash`` — the system prompt, so a changed critique framework marks it
  stale too;
- ``model`` — informational; a different model is a different opinion, not a
  stale one.

The deterministic ``report`` is never stored: it is free to recompute.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

SIDECAR_VERSION = 1
MAX_BODY = 200_000


def critiques_dir(outdir) -> Path:
    return Path(outdir) / "critiques"


def _safe(run_id: str) -> str:
    """A run id that is a legal, portable filename (``tag:down`` -> ``tag_down``)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(run_id))[:120] or "run"


def path_for(outdir, run_id: str) -> Path:
    return critiques_dir(outdir) / f"{_safe(run_id)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def run_hash(metrics: dict, notes: list | None = None) -> str:
    """The inputs that make this critique *about this play*."""
    return _digest({"metrics": metrics, "notes": notes or []})


def prompt_hash(system: str) -> str:
    return _digest({"system": system})


def load(outdir, run_id: str) -> dict | None:
    path = path_for(outdir, run_id)
    try:
        with open(path) as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not doc.get("body"):
        return None
    return doc


def save(outdir, critique: dict) -> Path:
    run_id = critique.get("run_id")
    if not run_id:
        raise ValueError("a critique needs a run_id")
    dest = path_for(outdir, run_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SIDECAR_VERSION,
        "run_id": run_id,
        "replay_md5": critique.get("replay_md5"),
        "beatmap_md5": critique.get("beatmap_md5"),
        "model": critique.get("model"),
        "prompt_hash": critique.get("prompt_hash"),
        "run_hash": critique.get("run_hash"),
        "created": critique.get("created") or _now(),
        "body": str(critique["body"])[:MAX_BODY],
    }
    tmp = dest.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False,
                              sort_keys=True) + "\n")
    os.replace(tmp, dest)
    return dest


def remove(outdir, run_id: str) -> bool:
    try:
        path_for(outdir, run_id).unlink()
        return True
    except FileNotFoundError:
        return False


def all_critiques(outdir) -> list[dict]:
    out = []
    directory = critiques_dir(outdir)
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("body") and doc.get("run_id"):
            out.append(doc)
    return out


def build(metrics: dict, notes: list, system: str, model: str, body: str,
          run_id: str) -> dict:
    """Assemble the sidecar for a critique that was just generated."""
    return {
        "run_id": run_id,
        "replay_md5": metrics.get("replay_md5"),
        "beatmap_md5": metrics.get("beatmap_md5"),
        "model": model,
        "prompt_hash": prompt_hash(system),
        "run_hash": run_hash(metrics, notes),
        "created": _now(),
        "body": body,
    }


def is_stale(stored: dict | None, metrics: dict, notes: list,
             system: str) -> bool:
    """True when the run, its notes, or the framework changed since the call."""
    if not stored:
        return False
    return (stored.get("run_hash") != run_hash(metrics, notes)
            or stored.get("prompt_hash") != prompt_hash(system))
