"""Stored answers — one canonical file per question about a selection.

An answer is authored data: it cost a call, and it must survive the index being
deleted. It lives in ``out/answers/<hash>.json``.

What makes it *this* answer is the pair (deterministic text, system prompt), so
the hash covers exactly that. The text is stored inside the file as well: it is
the model's entire input, and an answer sitting next to inputs it never saw would
be a lie. A changed corpus, a new note or a different question therefore makes a
different artifact — there is no "stale" state here by construction.

Before 0.25.0 these lived in ``out/critiques/scope/`` under the word "critique".
They are moved, not rewritten, the first time the directory is touched, and both
locations are still read so an upgrade never hides a paid-for answer.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .critiques import _safe  # one filename rule for authored sidecars
from .critiques import prompt_hash

SCHEMA_VERSION = 1
MAX_BODY = 200_000
LEGACY_DIR = Path("critiques") / "scope"


def answers_dir(outdir) -> Path:
    return Path(outdir) / "answers"


def legacy_dir(outdir) -> Path:
    return Path(outdir) / LEGACY_DIR


def path_for(outdir, digest: str) -> Path:
    return answers_dir(outdir) / f"{_safe(digest)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def migrate_legacy(outdir) -> int:
    """Move ``out/critiques/scope/*.json`` into ``out/answers/``. Returns the count.

    Moving a file is not rewriting it: the body, the hashes and the selection stay
    byte-identical, only the folder changes. Failures are ignored — a read-only
    corpus must still serve its answers.
    """
    source = legacy_dir(outdir)
    if not source.is_dir():
        return 0
    target = answers_dir(outdir)
    moved = 0
    for path in source.glob("*.json"):
        try:
            target.mkdir(parents=True, exist_ok=True)
            os.replace(path, target / path.name)
            moved += 1
        except OSError:
            continue
    try:
        source.rmdir()          # only succeeds when empty, which is the point
    except OSError:
        pass
    return moved


def build(*, digest: str, text: str, selection: dict, system: str, model: str,
          body: str, n_runs: int, n_maps: int, first: str | None,
          last: str | None, question: str | None = None) -> dict:
    """The sidecar for one answer. Authored: never recomputed."""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "answer",
        "hash": digest,
        "created": _now(),
        "model": model,
        "prompt_hash": prompt_hash(system),
        "system": system,
        "selection": selection,
        "question": question,
        "n_runs": n_runs,
        "n_maps": n_maps,
        "first_played": first,
        "last_played": last,
        "bytes": len(text.encode("utf-8")),
        "text": text[:MAX_BODY],
        "body": body[:MAX_BODY],
    }


def save(outdir, doc: dict) -> Path:
    path = path_for(outdir, doc["hash"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def load(outdir, digest: str) -> dict | None:
    for path in (path_for(outdir, digest),
                 legacy_dir(outdir) / f"{_safe(digest)}.json"):
        if not path.is_file():
            continue
        try:
            with open(path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None
    return None


def remove(outdir, digest: str) -> bool:
    gone = False
    for path in (path_for(outdir, digest),
                 legacy_dir(outdir) / f"{_safe(digest)}.json"):
        try:
            path.unlink()
            gone = True
        except OSError:
            continue
    return gone


def all_answers(outdir) -> list[dict]:
    """Every stored answer, newest first — for the index mirror."""
    found: dict[str, dict] = {}
    for directory in (answers_dir(outdir), legacy_dir(outdir)):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                with open(path) as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                continue
            if doc.get("kind") not in ("answer", "scope"):
                continue
            doc["source_path"] = os.fspath(path)
            found.setdefault(doc["hash"], doc)
    return sorted(found.values(), key=lambda d: d.get("created") or "",
                  reverse=True)
