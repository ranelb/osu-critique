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
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__, annotations, coach, covers, critiques, digest, index, scope
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
        # the tab is the only generator: for a one-run selection it stores a scope
        # artifact, and that is what this page shows when it exists
        system = coach.load_scope_prompt()
        scope_conn = index.open_readonly(out)
        built = None
        if scope_conn is not None:
            try:
                built = scope.build(
                    scope_conn, out,
                    {"runs": [run_id], "maps": [], "since": None, "until": None},
                    system=system)
            finally:
                scope_conn.close()
        page["scope_hash"] = built["hash"] if built else None
        page["scope_critique"] = (critiques.load_scope(out, built["hash"])
                                  if built else None)
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


    # ----------------------------------------------------------- critique --

    def _selection_state(request: Request, **extra):
        """Resolve the query into a selection, the built text, and every URL.

        The selection is the URL; nothing is remembered between requests. Each
        candidate row carries the link that adds it, each tray chip the link
        that removes it, so the picker needs no client-side state.
        """
        selection = scope.from_query(request.query_params)
        conn = index.open_readonly(out)
        if conn is None:
            return None
        try:
            built = scope.build(conn, out, selection, system=coach.load_scope_prompt())
            picked = {r["run_id"] for r in built["rows"]}
            picked_maps = {r["beatmap_md5"] for r in built["rows"]}
            mq = request.query_params.get("mq") or ""
            candidates = data.critique_candidates(conn, picked, picked_maps, mq)
            saved = data.scope_critiques(conn)
        finally:
            conn.close()

        def url(**changes):
            merged = dict(selection)
            merged.update(changes)
            return "/critique?" + urlencode(
                {k: ",".join(v) if isinstance(v, list) else (v or "")
                 for k, v in merged.items() if v})

        tray = []
        for run_id in selection["runs"]:
            tray.append({"label": run_id, "kind": "replay",
                         "remove": url(runs=[r for r in selection["runs"]
                                             if r != run_id])})
        for md5 in selection["maps"]:
            row = next((r for r in built["rows"] if r["beatmap_md5"] == md5), None)
            tray.append({"label": (row or {}).get("map_name") or md5, "kind": "map",
                         "remove": url(maps=[m for m in selection["maps"]
                                             if m != md5])})
        if selection["since"] or selection["until"]:
            tray.append({"label": " · ".join(x for x in (
                scope._PRESET_LABEL.get(selection["since"], selection["since"])
                or "", selection["until"] and f"until {selection['until']}" or "")
                if x), "kind": "range", "remove": url(since=None, until=None)})

        for row in candidates["runs"]:
            row["add"] = url(runs=selection["runs"] + [row["run_id"]])
        for row in candidates["maps"]:
            row["add"] = url(maps=selection["maps"] + [row["md5"]])
        presets = [{"label": label, "add": url(since=key, until=None)}
                   for key, label in (("today", "today"), ("session", "this session"),
                                      ("7d", "last 7 days"), ("30d", "last 30 days"))]
        return {"selection": selection, "built": built, "tray": tray,
                "candidates": candidates, "saved": saved, "presets": presets,
                "clear": "/critique", "mq": mq,
                "form": {"runs": ",".join(selection["runs"]),
                         "maps": ",".join(selection["maps"]),
                         "since": selection["since"] or "",
                         "until": selection["until"] or ""}}

    @app.get("/critique", response_class=HTMLResponse)
    def critique_page(request: Request):
        state = _selection_state(request)
        if state is None:
            return render("empty.html", request)
        return render("critique.html", request, **state,
                      max_bytes=scope.MAX_TEXT_BYTES,
                      stored=critiques.load_scope(out, state["built"]["hash"]) is not None,
                      llm_available=bool(_llm_key()),
                      llm_allowed=_llm_allowed(request))

    @app.get("/critique/{digest}", response_class=HTMLResponse)
    def critique_artifact(request: Request, digest: str):
        doc = critiques.load_scope(out, digest)
        if doc is None:
            raise HTTPException(status_code=404, detail="no such critique")
        return render("critique_artifact.html", request, doc=doc,
                      selection=doc.get("selection") or {},
                      reopen="/critique?" + urlencode(
                          {k: ",".join(v) if isinstance(v, list) else (v or "")
                           for k, v in (doc.get("selection") or {}).items() if v}))

    @app.post("/critique/generate")
    def critique_generate(request: Request, runs: str = Form(""),
                          maps: str = Form(""), since: str = Form(""),
                          until: str = Form("")):
        if not _llm_allowed(request):
            raise HTTPException(status_code=403,
                                detail="LLM routes are local-only (web.llm_remote = false)")
        if not _llm_key():
            raise HTTPException(status_code=400, detail=(
                "no LLM key configured: run `osu-critique setup` or set OSU_LLM_KEY"))
        selection = scope.from_query({"runs": runs, "maps": maps,
                                      "since": since, "until": until})
        system = coach.load_scope_prompt()
        conn = index.open_readonly(out)
        if conn is None:
            raise HTTPException(status_code=404, detail="no index")
        try:
            built = scope.build(conn, out, selection, system=system)
        finally:
            conn.close()
        if built["refused"]:
            raise HTTPException(
                status_code=413,
                detail=(f"this selection is {built['bytes'] // 1024} KB of summary; "
                        f"the limit is {scope.MAX_TEXT_BYTES // 1024} KB. "
                        "Narrow it and try again."))
        digest = built["hash"]
        if critiques.load_scope(out, digest) is not None:
            return _redirect(f"/critique/{digest}")
        if "text/event-stream" in request.headers.get("accept", ""):
            return StreamingResponse(
                _stream_scope(digest, built, selection, system),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        from ..coach import generate_critique
        try:
            text, model = generate_critique(system, built["text"])
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        critiques.save_scope(out, critiques.build_scope(
            digest=digest, text=built["text"], selection=selection, system=system,
            model=model, body=text, n_runs=built["n_runs"],
            n_maps=built["n_maps"], first=built["first"], last=built["last"]))
        _sync_notes()
        return _redirect(f"/critique/{digest}")

    def _stream_scope(digest, built, selection, system):
        q: queue.Queue = queue.Queue()
        result: dict = {}

        def worker():
            try:
                text, model = coach.generate_critique(system, built["text"],
                                                      on_delta=q.put)
                result["text"], result["model"] = text, model
            except Exception as exc:
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
        critiques.save_scope(out, critiques.build_scope(
            digest=digest, text=built["text"], selection=selection, system=system,
            model=result.get("model"), body=result.get("text") or "",
            n_runs=built["n_runs"], n_maps=built["n_maps"],
            first=built["first"], last=built["last"]))
        _sync_notes()
        yield "data: " + json.dumps({"done": True, "hash": digest,
                                     "url": f"/critique/{digest}"}) + "\n\n"
        yield "data: [DONE]\n\n"

    @app.post("/critique/{digest}/delete")
    def critique_delete(digest: str):
        critiques.remove_scope(out, digest)
        _sync_notes()
        return _redirect("/critique")

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
                index.sync_scope_critiques(conn, out)
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
