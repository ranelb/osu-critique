"""The digest: what happened since your last visit, written without an LLM.

Two jobs, both mechanical:

1. **ingest** — every exported ``.osr`` newer than the last digest is paired,
   analysed and indexed. Only new files: a re-run is a no-op, which is what
   makes it safe to wire to a timer.
2. **digest** — a markdown summary of the runs in that window: the plays
   themselves, how a typical one compares with the player's own history, and
   which maps deserve another attempt. Deterministic; no model, no keys.

The window is defined by ``out/digests/.last`` (an ISO timestamp plus the file's
own mtime for the ingest side).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

MARKER_NAME = ".last"
INGEST_MARKER_NAME = ".ingest"
WINDOW_NAME = ".window"


# ------------------------------------------------------------------ helpers --

def digests_dir(outdir) -> Path:
    return Path(outdir) / "digests"


def marker_path(outdir) -> Path:
    return digests_dir(outdir) / MARKER_NAME


def last_digest(outdir) -> tuple[str | None, float]:
    """``(iso_timestamp, epoch)`` of the previous digest, or ``(None, 0)``."""
    path = marker_path(outdir)
    try:
        text = path.read_text().strip()
        epoch = path.stat().st_mtime
    except OSError:
        return None, 0.0
    return (text or None), epoch


def window_path(outdir) -> Path:
    return digests_dir(outdir) / WINDOW_NAME


def last_window(outdir) -> dict:
    """What the previous digest covered: ``{"played_at": <newest play seen>}``.

    Deliberately the newest **play** in the corpus at that moment, not the time
    the digest ran: a digest that ran at 22:34 over plays whose newest was from
    the 24th must leave the window at the 24th, so the 25th's plays (exported
    afterwards) still count as new.
    """
    try:
        doc = json.loads(window_path(outdir).read_text())
        if isinstance(doc, dict):
            return doc
    except (OSError, ValueError):
        pass
    return {}


def ingest_marker_path(outdir) -> Path:
    return digests_dir(outdir) / INGEST_MARKER_NAME


def last_ingest(outdir) -> float:
    """The newest exported-file mtime that a previous ingest has already seen.

    Deliberately **not** "when the last digest ran": a digest that only
    summarised (``--no-ingest``) used to move the marker to *now* and thereby
    skip every file exported before it — which is exactly how a night of plays
    went missing. Falls back to the old marker's mtime for existing folders.
    """
    path = ingest_marker_path(outdir)
    try:
        return float(path.read_text().strip())
    except (OSError, ValueError):
        return last_digest(outdir)[1]


def _write_ingest_marker(outdir, epoch: float) -> None:
    path = ingest_marker_path(outdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{epoch:.3f}\n")


def _now() -> datetime:
    """Naive local time: it must compare lexicographically with ``played_at``,
    which comes from the replay's own local timestamp."""
    return datetime.now()


def _fmt(iso: str | None) -> str:
    return (iso or "")[:16].replace("T", " ") or "the beginning"


# ------------------------------------------------------------------- ingest --

def ingest(outdir=None, since_epoch: float = 0.0, limit: int | None = None,
           quiet: bool = False) -> dict:
    """Analyse every exported replay newer than ``since_epoch``.

    "Known" means the replay's md5 is already in the index, so a re-export or a
    second run costs nothing beyond the file mtime check.
    """
    from . import index
    from .config import outdir as _outdir
    from .io import pairing
    from .report import analyze

    out = Path(outdir or _outdir())
    started = time.time()
    stats = {"candidates": 0, "analysed": 0, "known": 0, "failed": 0,
             "seconds": 0.0, "tags": []}
    if limit is not None and limit <= 0:
        stats["seconds"] = round(time.time() - started, 1)
        return stats

    known = _known_replay_md5(out)

    def is_new(path):
        try:
            return os.path.getmtime(path) > since_epoch
        except OSError:
            return False

    pairs = pairing.pair_all(replay_filter=is_new)
    candidates = list(pairs if limit is None else pairs[:limit])
    stats["candidates"] = len(candidates)
    # advance the watermark only to the newest file that exists, never to "now":
    # a file written after this pass stays newer than the watermark and is
    # picked up next time, while a file exported *before* an earlier marker can
    # no longer be skipped by it
    stats["watermark"] = max([since_epoch] + [_mtime(r) for _s, r, _m in pairs]
                             + _export_mtimes())

    taken: set[str] = set()
    for _source, replay_path, map_path in candidates:
        md5 = _replay_md5(replay_path)
        if md5 and md5 in known:
            stats["known"] += 1
            continue
        tag = _tag(replay_path, taken)
        taken.add(tag)
        try:
            analyze(replay_path, map_path, tag=tag, outdir=out, console=False,
                    do_charts=False)
            stats["analysed"] += 1
            stats["tags"].append(tag)
            if not quiet:
                print(f"  analysed {tag}", file=sys.stderr)
        except Exception as exc:  # one bad replay must not stop the digest
            stats["failed"] += 1
            if not quiet:
                print(f"  ! skipped {os.path.basename(replay_path)}: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
    if stats["analysed"]:
        index.sweep(out, quiet=True)
    stats["seconds"] = round(time.time() - started, 1)
    return stats


def _mtime(path) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _export_mtimes() -> list[float]:
    """mtime of every exported .osr (one stat per file, no parsing)."""
    from .config import lazer_exports

    directory = Path(lazer_exports())
    if not directory.is_dir():
        return []
    return [_mtime(p) for p in directory.glob("*.osr")]


def _known_replay_md5(out: Path) -> set[str]:
    from . import index

    db = out / index.DB_FILENAME
    if not db.exists():
        index.sweep(out, quiet=True)
    conn = index.open_readonly(out)
    if conn is None:
        return set()
    try:
        return {r[0] for r in conn.execute(
            "SELECT replay_md5 FROM runs WHERE replay_md5 IS NOT NULL")}
    finally:
        conn.close()


def _replay_md5(path) -> str | None:
    try:
        import slider
        replay = slider.Replay.from_path(path, retrieve_beatmap=False)
        return getattr(replay, "replay_md5", None)
    except Exception:
        return None


def _tag(replay_path, taken) -> str:
    from .cli import _tag_from_replay

    return _tag_from_replay(replay_path, taken)


# ------------------------------------------------------------------- digest --

def _miss_rate(row) -> float | None:
    try:
        counts = json.loads(row["counts_recorded_json"] or "{}")
    except ValueError:
        return None
    n = row["n_objects"]
    if not counts or not n:
        return None
    return 100.0 * int(counts.get("miss") or 0) / n


def _history(conn, before: str | None) -> dict:
    """Prior runs' normalised scalars, for the percentile comparison."""
    sql = ("SELECT ur_pct_of_300, n_objects, counts_recorded_json FROM runs "
           "WHERE trust_ok = 1")
    args: tuple = ()
    if before:
        sql += " AND (played_at IS NULL OR played_at < ?)"
        args = (before,)
    timing, miss = [], []
    for row in conn.execute(sql, args):
        if row["ur_pct_of_300"] is not None:
            timing.append(row["ur_pct_of_300"])
        rate = _miss_rate(row)
        if rate is not None:
            miss.append(rate)
    return {"timing": timing, "miss": miss}


def _pct(value, values, lower_is_better=True):
    from .metrics.baseline import better_than_pct

    if value is None or len(values) < 8:
        return None
    return better_than_pct(value, values, lower_is_better)


def _new_rows(conn, since_played: str | None, fresh_tags: list[str]) -> list:
    """Plays after the window, plus whatever this run just ingested.

    The tags matter for the case the timestamp cannot see: a replay exported
    tonight for a play from last night. Ingest knows exactly which runs it just
    analysed, so those are included regardless of their ``played_at``.
    """
    where, args = [], []
    if since_played:
        where.append("(played_at IS NOT NULL AND played_at > ?)")
        args.append(since_played)
    fresh = [t for t in (fresh_tags or []) if t]
    if fresh:
        where.append("tag IN (" + ",".join("?" * len(fresh)) + ")")
        args.extend(fresh)
    sql = "SELECT * FROM runs" + (" WHERE " + " OR ".join(where) if where else "")
    sql += " ORDER BY played_at DESC"
    return conn.execute(sql, tuple(args)).fetchall()


def build(outdir=None, since: str | None = None, ingest_first: bool = True,
          write: bool = True, quiet: bool = False,
          export_first: bool | None = None) -> dict:
    """Produce the digest for the window since the last one.

    ``export_first`` (default: whatever ``export.enabled`` says) pulls new
    replays out of the osu! database before ingesting, so "digest now" means
    "get my latest plays and summarise them" rather than "read whatever someone
    else exported".
    """
    from . import export, index

    from .config import outdir as _outdir

    out = Path(outdir or _outdir())
    marker_iso, marker_epoch = last_digest(out)
    window = last_window(out)
    if since is None:
        since = window.get("played_at") or marker_iso

    export_stats = None
    if export_first is None:
        export_first = export.enabled()
    if export_first:
        try:
            export_stats = export.run()
        except export.ExportError as exc:
            export_stats = {"ok": False, "error": str(exc)}
        if not quiet:
            if export_stats.get("ok"):
                print(f"  exported {export_stats.get('exported', 0)} new replays",
                      file=sys.stderr)
            else:
                print(f"  ! export skipped: {export_stats.get('error')}",
                      file=sys.stderr)

    ingest_stats = {"candidates": 0, "analysed": 0, "known": 0, "failed": 0,
                    "seconds": 0.0, "tags": [], "watermark": 0.0}
    if ingest_first:
        ingest_stats = ingest(out, since_epoch=last_ingest(out), quiet=quiet)

    conn = index.open_readonly(out)
    if conn is None:
        index.sweep(out, quiet=True)
        conn = index.open_readonly(out)
    try:
        if since is None:
            # first digest: 24 hours if there is older history, else everything
            cutoff = (_now() - timedelta(hours=24)).isoformat(timespec="seconds")
            older = conn.execute(
                "SELECT 1 FROM runs WHERE played_at IS NOT NULL AND played_at < ? "
                "LIMIT 1", (cutoff,)).fetchone()
            if older:
                since = cutoff
        rows = _new_rows(conn, since, ingest_stats.get("tags") or [])
        history = _history(conn, since)
        maps = _map_blocks(conn, rows)
        # the window only advances over plays this digest actually reported;
        # a window over the whole corpus would silently swallow a play that was
        # in the index but not shown (that is how a night went missing)
        window_to = max((r["played_at"] for r in rows if r["played_at"]),
                        default=None)
    finally:
        if conn is not None:
            conn.close()

    now = _now()
    digest = {
        "generated": now.isoformat(timespec="seconds"),
        "window_from": since,
        "n_runs": len(rows),
        "n_maps": len({r["beatmap_md5"] for r in rows}),
        "runs": [_row_brief(r) for r in rows],
        "history": {
            "n": len(history["timing"]),
            "timing_pct": _pct(_median_timing(rows), history["timing"]),
            "timing_median": _median(history["timing"]),
            "miss_pct": _pct(_median_miss(rows), history["miss"]),
            "miss_median": _median(history["miss"]),
        },
        "maps": maps,
        "window_to": window_to,
        "ingest": ingest_stats,
        "export": export_stats,
        "export_enabled": bool(export_first),
    }
    scored = [r for r in digest["runs"] if r["accuracy"] is not None]
    if scored:
        digest["best"] = max(scored, key=lambda r: r["accuracy"])
        digest["worst"] = min(scored, key=lambda r: r["accuracy"])
    else:
        digest["best"] = digest["worst"] = None
    digest["window_label"] = _fmt(since)
    text = render(digest)
    digest["markdown"] = text
    if write:
        path = _write(out, now, text, digest)
        digest["path"] = str(path)
        marker_path(out).parent.mkdir(parents=True, exist_ok=True)
        marker_path(out).write_text(digest["generated"] + "\n")
        if digest.get("window_to"):
            window_path(out).write_text(json.dumps({
                "played_at": digest["window_to"],
            }, indent=1) + "\n")
        if ingest_first:
            _write_ingest_marker(out, float(ingest_stats.get("watermark") or 0.0))
    return digest


def _max_text(conn, column: str) -> str | None:
    try:
        return conn.execute(f"SELECT MAX({column}) FROM runs").fetchone()[0]
    except Exception:
        return None


def _median(values):
    vals = [v for v in values if v is not None]
    return float(statistics.median(vals)) if vals else None


def _median_timing(rows):
    return _median([r["ur_pct_of_300"] for r in rows])


def _median_miss(rows):
    return _median([_miss_rate(r) for r in rows])


def _miss_count(row) -> int:
    try:
        counts = json.loads(row["counts_recorded_json"] or "{}")
    except ValueError:
        return 0
    return int(counts.get("miss") or 0)


def _row_brief(row) -> dict:
    return {
        "when": (row["played_at"] or "")[:16].replace("T", " "),
        "map": row["map_name"],
        "mods": row["mod_string"],
        "accuracy": row["accuracy"],
        "ur": row["ur"],
        "miss": _miss_count(row),
        "trust": bool(row["trust_ok"]),
        "run_id": row["run_id"],
        "beatmap_md5": row["beatmap_md5"],
    }


def _map_blocks(conn, rows) -> list[dict]:
    """For maps in the window: is there a structure worth naming?

    Only maps with at least two stored attempts can say anything — with one
    attempt the digest says so instead of inventing a pattern.
    """
    from .metrics.attempts import build as build_attempts

    seen, blocks = set(), []
    for row in rows:
        md5 = row["beatmap_md5"]
        if not md5 or md5 in seen:
            continue
        seen.add(md5)
        attempts = conn.execute(
            "SELECT * FROM runs WHERE beatmap_md5 = ? ORDER BY played_at",
            (md5,)).fetchall()
        beatmap = conn.execute(
            "SELECT title, artist, creator, version, set_id FROM beatmaps "
            "WHERE beatmap_md5 = ?", (md5,)).fetchone()
        block = {"md5": md5, "map": row["map_name"], "n_attempts": len(attempts),
                 "new": 0, "stable": [], "volatile": [], "verdict": None,
                 "title": None, "artist": None, "creator": None,
                 "version": None, "set_id": None,
                 "sr": next((a["sr"] for a in attempts if a["sr"] is not None), None)}
        if beatmap is not None:
            block.update({k: beatmap[k] for k in
                          ("title", "artist", "creator", "version", "set_id")})
        block["new"] = sum(1 for a in attempts
                           if a["run_id"] in {r["run_id"] for r in rows})
        if len(attempts) >= 2:
            loaded = []
            for a in attempts:
                try:
                    with open(a["json_path"]) as fh:
                        loaded.append((a["json_path"], json.load(fh)))
                except (OSError, ValueError):
                    continue
            if len(loaded) >= 2:
                try:
                    cmp = build_attempts(loaded)["maps"][0]
                    block["stable"] = cmp.get("stable_weaknesses") or []
                    block["volatile"] = cmp.get("volatile") or []
                    block["verdict"] = cmp.get("verdict")
                except Exception:
                    pass
        blocks.append(block)
    return blocks


def _write(out: Path, now: datetime, text: str, data: dict) -> Path:
    """Markdown for humans/CLIs, JSON for the feed to render as a page."""
    directory = digests_dir(out)
    directory.mkdir(parents=True, exist_ok=True)
    stem = now.strftime("%Y-%m-%d_%H%M")
    path = directory / f"{stem}.md"
    path.write_text(text)
    stored = {k: v for k, v in data.items() if k not in ("markdown", "path")}
    (directory / f"{stem}.json").write_text(
        json.dumps(stored, indent=1, default=str, ensure_ascii=False) + "\n")
    return path


# ------------------------------------------------------------------ render --

def render(d: dict) -> str:
    lines = [f"# Digest — {d['generated'][:16].replace('T', ' ')}", ""]
    if d["n_runs"]:
        lines.append(f"**{d['n_runs']} new play{'' if d['n_runs'] == 1 else 's'} "
                     f"over {d['n_maps']} map{'' if d['n_maps'] == 1 else 's'}** "
                     f"since {_fmt(d['window_from'])}.")
    else:
        lines.append(f"**Nothing new** since {_fmt(d['window_from'])}.")
    exported = d.get("export") or {}
    if exported.get("exported"):
        lines.append(f"Exported {exported['exported']} replay"
                     f"{'' if exported['exported'] == 1 else 's'} from osu! first.")
    ingest = d.get("ingest") or {}
    if ingest.get("analysed") or ingest.get("failed") or ingest.get("candidates"):
        lines.append("")
        lines.append(f"Ingest: {ingest.get('analysed', 0)} analysed, "
                     f"{ingest.get('known', 0)} already known, "
                     f"{ingest.get('failed', 0)} failed "
                     f"({ingest.get('seconds', 0)}s).")
    if not d["n_runs"] and not ingest.get("candidates"):
        lines.append("")
        if exported.get("error"):
            lines.append(f"_No replays to read: {exported['error'].splitlines()[0]}_")
        elif not d.get("export_enabled"):
            lines.append("_No new exported replays, and pulling them out of osu! is "
                         "off. Run `osu-critique export --run`, or set "
                         "`export.enabled: true` so every digest fetches them._")
        else:
            lines.append("_osu! had no new scores to export since the last digest — "
                         "nothing was played, or the game was not running when the "
                         "export ran._")
    if not d["n_runs"]:
        return "\n".join(lines) + "\n"

    lines += ["", "## Plays", "",
              "| when | map | mods | acc | UR | miss | trust |",
              "|---|---|---|---|---|---|---|"]
    for r in d["runs"][:20]:
        lines.append(
            f"| {r['when']} | {r['map']} | {r['mods']} | "
            f"{r['accuracy'] * 100:.2f}% | {r['ur'] or 0:.0f} | {r['miss']:.0f} | "
            f"{'ok' if r['trust'] else 'differs'} |")
    if len(d["runs"]) > 20:
        lines.append(f"| … | {len(d['runs']) - 20} more | | | | | |")

    scored = [r for r in d["runs"] if r["accuracy"] is not None]
    if scored:
        best = max(scored, key=lambda r: r["accuracy"])
        worst = min(scored, key=lambda r: r["accuracy"])
        lines += ["", f"Best: **{best['accuracy'] * 100:.2f}%** — {best['map']} "
                      f"({best['mods']})  ",
                  f"Worst: **{worst['accuracy'] * 100:.2f}%** — {worst['map']} "
                  f"({worst['mods']})"]

    h = d["history"]
    lines += ["", "## Against your history", ""]
    if h["timing_pct"] is not None:
        lines.append(f"- timing spread: a typical play this session is better than "
                     f"**{h['timing_pct']:.0f}%** of {h['n']} earlier runs "
                     f"(median {h['timing_median']:.1f}% of the 300-window).")
    if h["miss_pct"] is not None:
        lines.append(f"- miss rate: better than **{h['miss_pct']:.0f}%** "
                     f"(median {h['miss_median']:.1f} per 100 objects).")
    if h["timing_pct"] is None and h["miss_pct"] is None:
        lines.append("- not enough stored runs to compare against yet.")
    lines.append("- aim-at-demand is not part of the digest: it needs the banded "
                 "per-object data, which `report --history <metrics>` computes for "
                 "one run at a time.")

    interesting = [b for b in d["maps"]
                   if b["stable"] or b["volatile"] or b["n_attempts"] > 1]
    lines += ["", "## Worth another look", ""]
    if not interesting:
        lines.append("- everything in this window was a first attempt: nothing "
                     "structural to compare yet.")
    for b in interesting[:8]:
        bits = []
        if b["stable"]:
            bits.append("consistent weakness: " + _names(b["stable"]))
        if b["volatile"]:
            bits.append("swings: " + _names(b["volatile"]))
        detail = "; ".join(bits) or "no structural signal"
        lines.append(f"- **{b['map']}** — {b['n_attempts']} attempt"
                     f"{'' if b['n_attempts'] == 1 else 's'} on record, "
                     f"{b['new']} new: {detail}")
    lines.append("")
    lines.append("_Deterministic digest: no model was called._")
    return "\n".join(lines) + "\n"


def _names(names, limit: int = 4) -> str:
    names = list(names)
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" (+{len(names) - limit} more)"


def load_digests(outdir) -> list[dict]:
    """The written digests, newest first (for the web feed)."""
    directory = digests_dir(outdir)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.md"), reverse=True):
        try:
            text = path.read_text()
            mtime = path.stat().st_mtime
        except OSError:
            continue
        data = None
        sidecar = path.with_suffix(".json")
        if sidecar.is_file():
            try:
                data = json.loads(sidecar.read_text())
            except (OSError, ValueError):
                data = None
        if data:
            data["worth"] = [b for b in data.get("maps", [])
                             if b.get("stable") or b.get("volatile")
                             or (b.get("n_attempts") or 0) > 1][:8]
        out.append({"name": path.name, "stem": path.stem, "text": text,
                    "mtime": mtime, "data": data})
    return out
