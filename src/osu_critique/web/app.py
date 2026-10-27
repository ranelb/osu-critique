"""The local web frontend (optional extra: ``pip install 'osu-critique[web]'``).

A second frontend, not a second implementation: every number here comes from
the index (a projection of ``out/*_metrics.json``) or from the analysis library
itself. Nothing in this package decides what a play means.

Run it with ``osu-critique serve``. It binds ``0.0.0.0:8765`` by default --
no auth, by the owner's explicit choice -- so anything on the network can read
the history. See ``docs/web.md``.
"""
from __future__ import annotations

import json
import queue
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__, annotations, covers, critiques, digest, index
from ..config import outdir as default_outdir
from . import data

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"

#: How many rows the object table renders before it says "and N more".
TABLE_LIMIT = 400


# ------------------------------------------------------------------ filters --

def pct(value, digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def num(value, digits: int = 1, dash: str = "—") -> str:
    return dash if value is None else f"{value:.{digits}f}"


def star(value) -> str:
    return "—" if value is None else f"{value:.1f}★"


def when(value) -> str:
    if not value:
        return "—"
    return value[:16].replace("T", " ")


def clock(seconds) -> str:
    if seconds is None:
        return "—"
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def ts(epoch) -> str:
    from datetime import datetime

    try:
        return datetime.fromtimestamp(float(epoch)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "—"


def mmss(ms) -> str:
    """Milliseconds -> ``m:ss.mmm`` (object times, window edges)."""
    if ms is None:
        return "—"
    total = max(0.0, float(ms)) / 1000.0
    minutes = int(total // 60)
    return f"{minutes}:{total - minutes * 60:06.3f}"


# --------------------------------------------------------------------- app ----

def create_app(outdir=None, index_on_boot: bool = True) -> FastAPI:
    out = Path(outdir or default_outdir())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if index_on_boot:
            _ensure_index(out)
        yield

    app = FastAPI(title="osu-critique", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.outdir = out
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    templates = Jinja2Templates(directory=TEMPLATES)
    templates.env.filters.update(pct=pct, num=num, star=star, when=when,
                                 clock=clock, mmss=mmss, ts=ts,
                                 fmt_t=annotations.fmt_time)
    templates.env.globals.update(
        version=__version__,
        table_limit=TABLE_LIMIT,
        brand="osu-critique",
    )
    app.state.templates = templates

    def render(name: str, request: Request, status_code: int = 200, **ctx):
        return templates.TemplateResponse(
            request, name, {"request": request, "outdir": str(out), **ctx},
            status_code=status_code)

    # ------------------------------------------------------------- pages --

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, q: str | None = None,
             sort: str = "recent", status: str | None = None,
             trust: str | None = None, offset: int = 0):
        conn = index.open_readonly(out)
        if conn is None:
            return render("empty.html", request)
        try:
            page = data.list_maps(conn, q=q, sort=sort, status=status,
                                  trust_only=(trust == "ok"),
                                  offset=max(0, offset))
        finally:
            conn.close()
        return render("index.html", request, **page, q=q or "",
                      status=status or "", trust=trust or "",
                      sorts=list(data.SORTS.items()))

    @app.get("/feed", response_class=HTMLResponse)
    def feed(request: Request):
        items = digest.load_digests(out)
        marker, _epoch = digest.last_digest(out)
        conn = index.open_readonly(out)
        n_new = 0
        if conn is not None:
            try:
                sql = "SELECT COUNT(*) FROM runs"
                args = ()
                if marker:
                    sql += " WHERE played_at > ?"
                    args = (marker,)
                n_new = conn.execute(sql, args).fetchone()[0]
            finally:
                conn.close()
        from datetime import datetime
        toc = [{"id": f"digest-{i}",
                "label": datetime.fromtimestamp(item["mtime"]).strftime("%d %b %H:%M"),
                "count": (item["data"] or {}).get("n_runs") or 0}
               for i, item in enumerate(items, 1) if item["data"]]
        return render("feed.html", request, items=items, marker=marker,
                      n_new=n_new, toc=toc)

    @app.get("/map/{beatmap_md5}", response_class=HTMLResponse)
    def map_page(request: Request, beatmap_md5: str, sort: str = "played_at"):
        conn = index.open_readonly(out)
        if conn is None:
            return render("empty.html", request)
        try:
            page = data.map_page(conn, beatmap_md5, sort=sort)
        finally:
            conn.close()
        if page is None:
            raise HTTPException(status_code=404, detail="no such beatmap")
        page["notes"] = annotations.for_map(out, beatmap_md5)
        page["toc"] = data.map_toc(page)
        return render("map.html", request, **page)

    @app.get("/map/{beatmap_md5}/attempts", response_class=HTMLResponse)
    def map_attempts(request: Request, beatmap_md5: str, sort: str = "played_at"):
        conn = index.open_readonly(out)
        if conn is None:
            raise HTTPException(status_code=404, detail="no index")
        try:
            page = data.map_page(conn, beatmap_md5, sort=sort)
        finally:
            conn.close()
        if page is None:
            raise HTTPException(status_code=404, detail="no such beatmap")
        return render("partials/attempts.html", request, **page)

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    def run_page(request: Request, run_id: str):
        conn = index.open_readonly(out)
        if conn is None:
            return render("empty.html", request)
        try:
            page = data.run_page(conn, run_id)
        finally:
            conn.close()
        if page is None:
            raise HTTPException(status_code=404, detail="no such run")
        page["notes"] = annotations.for_map(out, page["run"]["beatmap_md5"],
                                            page["run"]["replay_md5"])
        from ..coach import load_system_prompt
        flat = page["notes"]["map"] + page["notes"]["run"]
        stored = critiques.load(out, run_id)
        page["critique"] = stored
        page["critique_stale"] = critiques.is_stale(
            stored, page["metrics"], flat, load_system_prompt())
        page["llm_available"] = bool(_llm_key())
        page["llm_allowed"] = _llm_allowed(request)
        page["toc"] = data.run_toc(page)
        return render("run.html", request, **page)

    @app.get("/run/{run_id}/report.txt", response_class=PlainTextResponse)
    def run_report_text(run_id: str):
        """The deterministic report as plain text — what the copy button copies.

        Same `report_sections` data the page renders, so the pasted text cannot
        drift from the cards, and it is the seam the critique tab will feed to
        a model later.
        """
        conn = index.open_readonly(out)
        if conn is None:
            raise HTTPException(status_code=404, detail="no index")
        try:
            row = data.get_run(conn, run_id)
        finally:
            conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail="no such run")
        text = data.report_text(data._row_dict(row))
        if not text:
            raise HTTPException(status_code=404, detail="no metrics for this run")
        return PlainTextResponse(
            text, headers={"Content-Disposition": f'inline; filename="{run_id}.txt"'})

    # -------------------------------------------------------------- json --

    @app.get("/api/runs")
    def api_runs(q: str | None = None, sort: str = "recent",
                 status: str | None = None, trust: str | None = None,
                 offset: int = 0, limit: int = 120):
        conn = index.open_readonly(out)
        if conn is None:
            return JSONResponse({"maps": [], "total": 0})
        try:
            return data.list_maps(conn, q=q, sort=sort, status=status,
                                  trust_only=(trust == "ok"),
                                  offset=max(0, offset), limit=min(limit, 500))
        finally:
            conn.close()

    @app.get("/api/map/{beatmap_md5}")
    def api_map(beatmap_md5: str, sort: str = "played_at"):
        conn = index.open_readonly(out)
        if conn is None:
            raise HTTPException(status_code=404, detail="no index")
        try:
            page = data.map_page(conn, beatmap_md5, sort=sort)
        finally:
            conn.close()
        if page is None:
            raise HTTPException(status_code=404, detail="no such beatmap")
        page.pop("cross_attempt", None)
        return page

    @app.get("/api/objects/{run_id}")
    def api_objects(run_id: str):
        """The per-object record, as written by ``analyze`` (no reshaping)."""
        conn = index.open_readonly(out)
        if conn is None:
            raise HTTPException(status_code=404, detail="no index")
        try:
            run = index.get_run(conn, run_id)
        finally:
            conn.close()
        if run is None:
            raise HTTPException(status_code=404, detail="no such run")
        path = run["objects_path"]
        if not path or not Path(path).is_file():
            raise HTTPException(status_code=404, detail="no object records for this run")
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=f"unreadable objects: {exc}")
        return JSONResponse(doc)

    @app.get("/api/cover/{beatmap_md5}")
    def api_cover(beatmap_md5: str, size: str = "card"):
        conn = index.open_readonly(out)
        if conn is None:
            raise HTTPException(status_code=404, detail="no index")
        try:
            bm = index.get_beatmap(conn, beatmap_md5)
        finally:
            conn.close()
        if bm is None or not bm["set_id"]:
            raise HTTPException(status_code=404, detail="no cover for this beatmap")
        if size not in covers.SIZES:
            raise HTTPException(status_code=400, detail="size is 'card' or 'hero'")
        path = covers.ensure(out, bm["set_id"], size)
        if path is None:
            raise HTTPException(status_code=404, detail="cover unavailable")
        return FileResponse(path, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=604800"})

    # ------------------------------------------------------------- digest --

    _digest_lock = threading.Lock()

    @app.post("/feed/digest")
    def run_digest(since: str = Form("")):
        """Run the digest now (ingest + summary). One at a time."""
        if not _digest_lock.acquire(blocking=False):
            raise HTTPException(status_code=409,
                                detail="a digest is already running — give it a moment")
        try:
            doc = digest.build(outdir=out, since=since.strip() or None,
                               ingest_first=True, quiet=True)
        except Exception as exc:  # noqa: BLE001 - show the reason, not a traceback
            raise HTTPException(status_code=500, detail=(
                f"digest failed: {type(exc).__name__}: {exc}"))
        finally:
            _digest_lock.release()
        print(f"digest: {doc.get('n_runs', 0)} new runs, {doc.get('path')}",
              file=sys.stderr)
        return _redirect("/feed")

    # -------------------------------------------------------- annotations --

    def _sync_notes():
        """Mirror the sidecars into the index (best-effort: files are truth)."""
        try:
            conn = index.connect(index.db_path(out))
            try:
                index.sync_annotations(conn, out)
                index.sync_critiques(conn, out)
                conn.commit()
            finally:
                conn.close()
        except Exception:  # a locked index must not lose the note
            pass

    def _tags(raw: str) -> list[str]:
        return [t for t in str(raw or "").replace(",", " ").split() if t]

    def _redirect(url: str) -> RedirectResponse:
        # only same-site paths: a form field must not become an open redirect
        if not url.startswith("/") or url.startswith("//"):
            url = "/"
        return RedirectResponse(url, status_code=303)

    @app.post("/map/{beatmap_md5}/annotations")
    def add_map_note(beatmap_md5: str, body: str = Form(""),
                     t: str = Form(""), tag: str = Form("")):
        text = body.strip()
        if not text:
            raise HTTPException(status_code=400, detail="an empty note is not a note")
        try:
            t_map = annotations.parse_time(t)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        annotations.add(out, beatmap_md5, text, scope="map", t_map=t_map,
                        tags=_tags(tag))
        _sync_notes()
        return _redirect(f"/map/{beatmap_md5}")

    @app.post("/run/{run_id}/annotations")
    def add_run_note(run_id: str, body: str = Form(""), t_map: str = Form(""),
                     tag: str = Form(""), scope: str = Form("run")):
        conn = index.open_readonly(out)
        if conn is None:
            raise HTTPException(status_code=404, detail="no index")
        try:
            run = index.get_run(conn, run_id)
        finally:
            conn.close()
        if run is None:
            raise HTTPException(status_code=404, detail="no such run")
        text = body.strip()
        if not text:
            raise HTTPException(status_code=400, detail="an empty note is not a note")
        try:
            t = annotations.parse_time(t_map)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        scoped = "map" if scope == "map" else "run"
        annotations.add(out, run["beatmap_md5"], text, scope=scoped,
                        replay_md5=run["replay_md5"], t_map=t, tags=_tags(tag))
        _sync_notes()
        return _redirect(f"/run/{run_id}")

    @app.post("/annotations/{note_id}/delete")
    def delete_note(note_id: str, next: str = Form("/")):
        md5 = annotations.find_owner(out, note_id)
        if md5:
            annotations.remove(out, md5, note_id)
            _sync_notes()
        return _redirect(next)

    # ---------------------------------------------------------- critiques --

    def _llm_key():
        from ..config import llm_key
        return llm_key()

    def _llm_allowed(request: Request) -> bool:
        """``web.llm_remote`` gates the routes that spend money.

        Default true (the owner's choice); when false, only a loopback client
        may ask for a critique — reading the pages stays open either way.
        """
        from ..config import get
        value = get("web.llm_remote", "OSU_WEB_LLM_REMOTE", True)
        if isinstance(value, str):
            allowed = value.strip().lower() not in ("0", "false", "no", "off")
        else:
            allowed = bool(value)
        if allowed:
            return True
        host = request.client.host if request.client else ""
        return host in ("127.0.0.1", "::1", "localhost")

    def _critique_inputs(run_id: str):
        conn = index.open_readonly(out)
        if conn is None:
            raise HTTPException(status_code=404, detail="no index")
        try:
            run = index.get_run(conn, run_id)
        finally:
            conn.close()
        if run is None:
            raise HTTPException(status_code=404, detail="no such run")
        metrics = data._metrics_at(run["json_path"]) or {}
        if not metrics:
            raise HTTPException(status_code=409, detail="the metrics artifact is missing")
        notes = annotations.for_map(out, run["beatmap_md5"], run["replay_md5"])
        return run, metrics, notes["map"] + notes["run"]

    @app.post("/run/{run_id}/critique")
    def make_critique(request: Request, run_id: str):
        if not _llm_allowed(request):
            raise HTTPException(status_code=403,
                                detail="LLM routes are local-only (web.llm_remote = false)")
        if not _llm_key():
            raise HTTPException(status_code=400, detail=(
                "no LLM key configured: run `osu-critique setup` or set OSU_LLM_KEY"))
        _run, metrics, notes = _critique_inputs(run_id)

        from ..coach import generate_critique, load_system_prompt, prepare_critique
        system, user, _notes = prepare_critique(metrics, out)

        if "text/event-stream" in request.headers.get("accept", ""):
            return StreamingResponse(
                _stream_critique(run_id, metrics, notes, system, user),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        try:
            text, model = generate_critique(system, user)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        doc = critiques.build(metrics, notes, system, model, text, run_id=run_id)
        critiques.save(out, doc)
        _sync_notes()
        return _redirect(f"/run/{run_id}")

    def _stream_critique(run_id, metrics, notes, system, user):
        """SSE: deltas as they arrive, then the saved sidecar's metadata."""
        q: queue.Queue = queue.Queue()
        result: dict = {}

        def worker():
            try:
                from ..coach import generate_critique
                text, model = generate_critique(system, user, on_delta=q.put)
                result["text"] = text
                result["model"] = model
            except Exception as exc:  # surfaced to the browser, never silent
                result["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            chunk = q.get()
            if chunk is None:
                break
            yield "data: " + json.dumps({"delta": chunk}) + "\n\n"
        if result.get("error"):
            yield "data: " + json.dumps({"error": result["error"]}) + "\n\n"
            yield "data: [DONE]\n\n"
            return
        doc = critiques.build(metrics, notes, system, result.get("model"), 
                              result.get("text") or "", run_id=run_id)
        critiques.save(out, doc)
        _sync_notes()
        yield "data: " + json.dumps({"done": True, "model": doc["model"],
                                     "created": doc["created"]}) + "\n\n"
        yield "data: [DONE]\n\n"

    @app.post("/run/{run_id}/critique/delete")
    def delete_critique(run_id: str, next: str = Form("/")):
        critiques.remove(out, run_id)
        _sync_notes()
        return _redirect(next)

    @app.get("/run/{run_id}/frames")
    def frames(run_id: str):
        """Reserved for replay playback: the seam exists, the renderer does not."""
        return JSONResponse(
            {"detail": "playback is not implemented; this route is reserved so "
                       "adding it needs no schema change."}, status_code=501)

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz():
        return "ok"

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, exc: StarletteHTTPException):
        # API routes and the streaming client get JSON; a plain form POST gets
        # a readable page
        wants_json = (request.url.path.startswith("/api/")
                      or "text/event-stream" in request.headers.get("accept", ""))
        if wants_json:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return render("error.html", request, status_code=exc.status_code,
                      code=exc.status_code, detail=exc.detail)

    return app


# ------------------------------------------------------------------ startup --

def _ensure_index(out: Path) -> dict:
    """Sweep on boot when the index is missing, stale, or from another build.

    A derived DB written by an older release is rebuilt without asking: the
    server refusing to start after an upgrade would be worse than the rebuild.
    """
    if not (out / index.DB_FILENAME).exists():
        return index.sweep(out, quiet=True)
    try:
        drift = index.check(out)
    except index.SchemaMismatch:
        return index.sweep(out, rebuild=True, quiet=True)
    if drift.get("ok"):
        return {"runs": 0, "skipped": True}
    return index.sweep(out, quiet=True)
