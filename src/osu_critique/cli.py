"""osu-critique command line interface.

Subcommands:
  analyze <replay.osr> <map.osu> [tag]   analyze a single replay (zero keys)
  pair              resolve replay->map pairs (no analysis)
  batch             pair + analyze every available replay + aggregate
  paths             show resolved (auto-detected) paths
  prompt  [metrics] [--baseline] [--profile]   print the critique prompt (BYO AI)
  report  <metrics.json> [--baseline]    deterministic critique (no LLM, no keys)
                                         (adds a rolling baseline vs your stored runs)
  attempts [metrics.json|dir]            cross-attempt structure for one map
  coach   <metrics.json|dir> [--all] [--baseline] [--profile]   AI critique (BYO OSU_LLM_KEY)
  profile <username>                     fetch osu! profile (BYO osu API creds)
  setup   [--show]                       first-time configuration wizard
  index   [--rebuild|--check]            build / refresh out/index.sqlite
  serve   [--host] [--port]              run the local web frontend (needs [web])
  annotate add|list|rm                   human notes the coach reads (map or run scoped)
  export  [--install|--run]              opt-in replay export from the osu! database
  digest  [--since] [--no-ingest]        what's new since your last digest (no LLM)
         [--no-export]                 (it exports first when export.enabled)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .config import outdir
from .io import pairing
from .metrics.breakdown import build as build_breakdown
from .metrics.breakdown import console_lines as breakdown_lines
from .report import analyze, console_summary


# ------------------------------------------------------------- commands ----


def cmd_analyze(args):
    metrics = analyze(args.replay, args.map, tag=args.tag or "run",
                      do_charts=args.charts, outdir=args.outdir,
                      write_objects=not args.no_objects,
                      write_aim=not args.no_aim,
                      write_autopsy=not args.no_autopsy)
    console_summary(metrics)
    return 0


def cmd_serve(args):
    """Run the local web frontend (optional extra: osu-critique[web])."""
    try:
        import uvicorn
    except ImportError:
        print("error: the web frontend needs the [web] extra:\n"
              "  pip install 'osu-critique[web]'", file=sys.stderr)
        return 2
    try:
        from .web.app import create_app
    except ImportError as exc:
        print(f"error: cannot load the web frontend ({exc})\n"
              "  pip install 'osu-critique[web]'", file=sys.stderr)
        return 2

    from .config import get
    host = args.host or str(get("web.host", "OSU_WEB_HOST", "0.0.0.0"))
    port = int(args.port or get("web.port", "OSU_WEB_PORT", 8765))
    out = args.outdir or outdir()
    app = create_app(outdir=out, index_on_boot=not args.no_index)

    shown = "localhost" if host in ("0.0.0.0", "::") else host
    print(f"osu-critique web  http://{shown}:{port}   (out: {out})")
    if host in ("0.0.0.0", "::"):
        print("  bound to every interface, no auth: anything on this network can "
              "read the history")
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except OSError as exc:
        print(f"error: cannot bind {host}:{port}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        pass
    return 0


def cmd_export(args):
    """Opt-in replay export from osu!lazer's database (BeatmapExporter)."""
    from . import export

    if args.install:
        try:
            path = export.install(force=args.force)
        except export.ExportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"installed {path}")

    statuses = None
    if args.status is not None:
        statuses = [s for s in args.status.replace(",", " ").split() if s]

    if args.run:
        try:
            result = export.run(filter_statuses=statuses, timeout=args.timeout,
                                prune_player=args.prune_player)
        except export.ExportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"export: {result['exported']} new of {result['total']} score "
                  f"replays ({result['beatmaps']} beatmaps) in {result['seconds']}s")
            if result["pruned"]:
                print(f"  pruned {len(result['pruned'])} replays from other players")
            if result["dest"]:
                print(f"  dest: {result['dest']}")
        return 0 if result["ok"] else 2

    status = export.status()
    if args.json:
        print(json.dumps(status, indent=2))
        return 0
    print(f"export: {'enabled' if status['enabled'] else 'disabled'}"
          f"  (platform {status['platform']}, manifest {status['manifest_version']})")
    print(f"  binary:   {status['binary'] or 'not installed — run --install'}")
    print(f"  exports:  {status['exports_dir']}  ({status['replays_on_disk']} .osr)")
    print(f"  statuses: {', '.join(status['statuses'])}")
    if not status["enabled"]:
        print("  disabled by default: set export.enabled = true (or "
              "OSU_EXPORT_ENABLED=1) to let it touch the osu! database")
    return 0


def cmd_digest(args):
    """What's new since the last digest — deterministic, no LLM."""
    from . import digest

    try:
        doc = digest.build(outdir=args.outdir, since=args.since,
                           ingest_first=not args.no_ingest,
                           write=not args.stdout,
                           export_first=False if args.no_export else None)
    except Exception as exc:  # noqa: BLE001 - the CLI reports, never tracebacks
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(doc, indent=2, default=str))
        return 0
    if doc.get("path"):
        print(f"digest: {doc['path']}", file=sys.stderr)
    print(doc["markdown"])
    return 0


def cmd_annotate(args):
    """Add, list or remove human annotations (canonical sidecars under out/)."""
    from . import annotations, index

    root = args.outdir or outdir()

    if args.action == "add":
        body = " ".join(args.text).strip()
        if not body:
            print("error: empty note", file=sys.stderr)
            return 2
        try:
            t_map = annotations.parse_time(args.t)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        scope = "run" if args.run else "map"
        try:
            note = annotations.add(root, args.map, body, scope=scope,
                                   replay_md5=args.run, t_map=t_map,
                                   tags=args.tag)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        # keep the index in step immediately: the web server may be running
        try:
            conn = index.connect(index.db_path(root))
            try:
                index.sync_annotations(conn, root)
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:  # annotations saved; the mirror can wait
            print(f"  ! index not updated: {exc}", file=sys.stderr)
        where = f"run {args.run[:8]}" if args.run else "map"
        print(f"added note {note['note_id']} ({where}) to {args.map}")
        return 0

    if args.action == "rm":
        md5 = args.map or annotations.find_owner(root, args.id)
        if not md5:
            print(f"error: no note {args.id!r} in {root}/annotations", file=sys.stderr)
            return 2
        if not annotations.remove(root, md5, args.id):
            print(f"error: note {args.id!r} not found under {md5}", file=sys.stderr)
            return 2
        try:
            conn = index.connect(index.db_path(root))
            try:
                index.sync_annotations(conn, root)
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
        print(f"removed note {args.id} from {md5}")
        return 0

    # list
    if args.map:
        groups = annotations.for_map(root, args.map, args.run)
        notes = [*groups["map"], *groups["run"]]
    else:
        notes = annotations.all_notes(root)
        if args.run:
            notes = [n for n in notes if n["replay_md5"] == args.run]
    if args.json:
        print(json.dumps(notes, indent=2, ensure_ascii=False))
        return 0
    if not notes:
        print("no annotations")
        return 0
    for n in notes:
        stamp = annotations.fmt_time(n["t_map"]) or "          "
        where = "run " if n["scope"] == "run" else "map "
        tags = f"  [{', '.join(n['tags'])}]" if n.get("tags") else ""
        md5 = n.get("beatmap_md5") or args.map or "?"
        print(f"{n['note_id']}  {where} {stamp}  {md5[:12]}  {n['body']}{tags}")
    return 0


def cmd_index(args):
    """Build or refresh the derived SQLite index over out/"""
    from . import index

    if args.check:
        report = index.check(args.outdir)
        if args.json:
            print(json.dumps(report, indent=2))
        elif report.get("note"):
            print(f"index: {report['note']} ({report['index']})")
        else:
            print(f"index: {report['index']}")
            print(f"  new     {len(report['new'])}")
            print(f"  updated {len(report['updated'])}")
            print(f"  missing {len(report['missing'])}")
            for label in ("new", "updated", "missing"):
                for name in report[label][:5]:
                    print(f"    {label}: {name}")
                if len(report[label]) > 5:
                    print(f"    {label}: ... and {len(report[label]) - 5} more")
        return 0 if report["ok"] else 1

    try:
        stats = index.sweep(args.outdir, rebuild=args.rebuild, quiet=args.quiet)
    except index.SchemaMismatch as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print(f"index: {stats['runs']} runs, {stats['beatmaps']} beatmaps "
              f"-> {index.db_path(args.outdir)}")
        print(f"  added {stats['added']}, updated {stats['updated']}, "
              f"unchanged {stats['unchanged']}, removed {stats['removed']}, "
              f"failed {stats['failed']} ({stats['seconds']}s)")
    return 1 if stats["failed"] else 0


def cmd_pair(args):
    for source, rp, mp in pairing.pair_all():
        print(f"  [{source:7s}] {rp}  ->  {mp}")
    return 0


def cmd_batch(args):
    pairs = pairing.pair_all()
    print(f"\npaired {len(pairs)} replay+map sets\n")

    rows = []
    tags = set()
    for source, rp, mp in pairs:
        tag = _tag_from_replay(rp, tags)
        try:
            metrics = analyze(rp, mp, tag=tag, do_charts=args.charts,
                              outdir=args.outdir, console=False,
                              write_objects=not args.no_objects,
                              write_aim=not args.no_aim,
                              write_autopsy=not args.no_autopsy)
            console_summary(metrics)
        except Exception as e:  # one bad replay must not lose the whole sweep
            print(f"  !! skipped {tag} ({rp}): {type(e).__name__}: {e}", file=sys.stderr)
            continue
        rows.append(metrics)
        print()

    _aggregate(rows)
    return 0


def _load_objects(metrics_path):
    """The sibling ``<tag>_objects.json`` for a metrics file, or None."""
    base = os.path.basename(metrics_path)
    if not base.endswith("_metrics.json"):
        return None
    obj_path = os.path.join(os.path.dirname(metrics_path),
                            base[:-len("_metrics.json")] + "_objects.json")
    if not os.path.isfile(obj_path):
        return None
    with open(obj_path) as f:
        doc = json.load(f)
    return doc.get("objects") if isinstance(doc, dict) else doc


def cmd_breakdown(args):
    """How a play breaks down: speed cliff, reversal buckets, cascades, ramp."""
    try:
        metrics = _load_metrics(args.metrics_json)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    block = metrics.get("breakdown")
    if block is None:                      # older metrics: recompute from objects
        objs = _load_objects(args.metrics_json)
        if objs is None:
            print(f"error: {args.metrics_json!r} has no breakdown block and no "
                  "sibling _objects.json; re-run `analyze` without --no-objects",
                  file=sys.stderr)
            return 2
        block = build_breakdown(objs)
    if args.json:
        print(json.dumps(block, indent=2, default=float))
        return 0
    print(f"=== {metrics.get('map')} ({metrics.get('tag')}) ===")
    trust = (metrics.get("trust") or {}).get("trustworthy")
    print("\n".join(breakdown_lines(block, trust)))
    return 0


def _rows_and_outdir(args):
    """The metrics rows to operate on, and the outdir their caches live in."""
    from .coach import _load_metrics_dir
    from .config import outdir as _outdir
    target = getattr(args, "path_or_dir", None) or str(_outdir())
    if os.path.isfile(target):
        rows = [_load_metrics(target)]
        default = os.path.dirname(os.path.abspath(target))
    else:
        rows = [m for _, m in _load_metrics_dir(target)]
        default = target
    return rows, (args.outdir or default)


def _stars_or_pp(args, kind):
    from .metrics import difficulty as D
    rows, outdir_path = _rows_and_outdir(args)
    if not rows:
        print("error: no *_metrics.json files to rate", file=sys.stderr)
        return 2
    index = D.load_index(outdir_path, getattr(args, "lazer_files", None))
    try:
        if kind == "stars":
            cache_path = os.path.join(outdir_path, "stars_by_md5.json")
            cache = D._load_json(cache_path)
            cache = D.build_stars(rows, index, cache, player=args.player)
        else:
            cache_path = os.path.join(outdir_path, "pp_by_replay.json")
            cache = D._load_json(cache_path)
            cache = D.build_pp(rows, index, cache, player=args.player)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    with open(cache_path, "w") as f:
        json.dump(cache, f)
    print(f"{kind}: {len(cache)} entries -> {cache_path}")
    return 0


def cmd_stars(args):
    return _stars_or_pp(args, "stars")


def cmd_pp(args):
    return _stars_or_pp(args, "pp")


def cmd_status(args):
    """Ranked / leaderboard-only / unranked split over the stored runs."""
    from .io import status as S
    from .metrics import difficulty as D
    rows, outdir_path = _rows_and_outdir(args)
    if not rows:
        print("error: no *_metrics.json files to classify", file=sys.stderr)
        return 2
    index = D.load_index(outdir_path, None)
    cache_path = os.path.join(outdir_path, "beatmap_status.json")
    cache = S._load_json(cache_path)
    try:
        cache, md5_to_id = S.build_statuses(rows, index, cache=cache,
                                            cache_path=cache_path,
                                            player=args.player, log=print)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"status: {len(md5_to_id)}/{len({m.get('beatmap_md5') for m in rows})} "
          "played maps carry an online BeatmapID")
    s = S.summarise(rows, cache, md5_to_id, player=args.player)
    known = max(1, s["known"])
    print(f"\nplays: {s['plays']}  (status known for {s['known']});  "
          f"{s['total_hours']:.1f} h in-game")
    print(f"  {'status':<12} {'plays':>6} {'share':>6} {'hours':>7} {'h-share':>8}  bucket")
    for status, c in sorted(s["counts"].items(), key=lambda kv: -kv[1]):
        h = s["hours"].get(status, 0.0)
        share = 100.0 * h / max(0.01, s["total_hours"])
        print(f"  {status:<12} {c:6d} {100*c/known:5.1f}% {h:6.2f} {share:7.1f}%  "
              f"{S.classify(status)}")
    return 0


def cmd_prompt(args):
    """Print the critique-framework prompt; with a metrics JSON (or a folder of
    *_metrics.json), print a full ready-to-paste prompt (system + data)."""
    from .coach import (build_multi_user_message, build_user_message,
                        enrich_rows, load_system_prompt, _load_metrics_dir)
    system = load_system_prompt(args.prompt)
    if args.metrics_json and os.path.isdir(args.metrics_json):
        rows = _load_metrics_dir(args.metrics_json)
        if not rows:
            print(f"error: no *_metrics.json files in {args.metrics_json!r}",
                  file=sys.stderr)
            return 2
        profile = None
        if args.profile:
            from .profile import fetch_profile
            profile = fetch_profile(args.profile, allow_scrape=args.scrape or None)
        enrich_rows(rows, args.metrics_json)
        from .annotations import all_notes
        wanted = {m.get("beatmap_md5") for _n, m in rows if m.get("beatmap_md5")}
        notes = [n for n in all_notes(args.metrics_json)
                 if n["beatmap_md5"] in wanted]
        print(system)
        print("\n\n" + build_multi_user_message(rows, profile, notes=notes))
        return 0
    if args.metrics_json:
        try:
            metrics = _load_metrics(args.metrics_json)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        baseline = None
        if args.baseline:
            with open(args.baseline) as f:
                baseline = json.load(f)
        profile = None
        if args.profile:
            from .profile import fetch_profile
            profile = fetch_profile(args.profile, allow_scrape=args.scrape or None)
        enrich_rows([(os.path.basename(args.metrics_json), metrics)],
                    os.path.dirname(os.path.abspath(args.metrics_json)))
        from .annotations import for_metrics
        notes = for_metrics(metrics,
                            os.path.dirname(os.path.abspath(args.metrics_json)))
        print(system)
        print("\n\n" + build_user_message(metrics, baseline, profile, notes=notes))
    else:
        print(system)
    return 0


def _load_metrics(path):
    """Load a metrics JSON with a helpful error instead of a raw traceback."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(
            f"no such metrics file: {path!r} — run `osu-critique analyze "
            "<replay.osr> <map.osu> <tag>` first (it writes out/<tag>_metrics.json)")
    except json.JSONDecodeError:
        raise RuntimeError(f"{path!r} is not valid metrics JSON — "
                           "run `osu-critique analyze` to generate it")


def cmd_report(args):
    from .coach import _load_metrics_dir
    import os as _os
    if _os.path.isdir(args.metrics_json):
        rows = _load_metrics_dir(args.metrics_json)
        if not rows:
            print(f"error: no *_metrics.json files in {args.metrics_json!r}",
                  file=sys.stderr)
            return 2
        _aggregate([m for _, m in rows])
        from .metrics.attempts import build as _attempts_build
        block = _attempts_build(rows)
        if block["n_repeated"]:
            print(f"\n{block['n_repeated']} map(s) have more than one attempt — "
                  "run `osu-critique attempts <dir>` for cross-attempt structure "
                  "(stable weaknesses vs one-off noise)")
        return 0
    try:
        metrics = _load_metrics(args.metrics_json)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    baseline = None
    if args.baseline:
        try:
            with open(args.baseline) as f:
                baseline = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"error: cannot read baseline {args.baseline!r}: {e}",
                  file=sys.stderr)
            return 2
    text = render_report(metrics, baseline)
    rows = [] if args.no_history else _history_rows(args.history)
    if rows:
        from .metrics.baseline import history_report, describe as describe_history
        block = history_report(metrics, rows)
        text += "\n\n" + "\n".join(describe_history(block))
    print(text)
    return 0


def _history_rows(history):
    """The stored runs to compare against: the given dir, or the output dir."""
    from .coach import _load_metrics_dir
    target = history if history else str(outdir())
    if not os.path.isdir(target):
        return []
    return _load_metrics_dir(target)


def cmd_coach(args):
    from .coach import coach as run_coach
    if args.all:
        from .config import outdir
        args.metrics_json = str(outdir())
    profile = None
    if args.profile:
        from .profile import fetch_profile
        profile = fetch_profile(args.profile)
        print(f"profile: {profile.get('username')} "
              f"#{profile.get('global_rank')} · {profile.get('pp')}pp · "
              f"{profile.get('play_time_hours')}h", file=sys.stderr)
    try:
        text = run_coach(args.metrics_json, args.baseline, profile,
                         model=args.model, prompt_file=args.prompt)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.save:
        _save_critique(args, text)
    return 0


def cmd_critique(args):
    """The same builder the critique tab uses, without a browser."""
    from . import critiques, index, scope
    from .coach import load_scope_prompt
    from .config import outdir

    out = outdir()
    try:
        conn = index.open_readonly(index.db_path(out))
    except index.SchemaMismatch as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if conn is None:
        print("error: no index — run `osu-critique index` first", file=sys.stderr)
        return 2
    selection = {"runs": [x.strip() for x in args.runs.split(",") if x.strip()],
                 "maps": [x.strip() for x in args.maps.split(",") if x.strip()],
                 "since": args.since, "until": args.until}
    system = load_scope_prompt(args.prompt)
    try:
        built = scope.build(conn, out, selection, system=system)
    finally:
        conn.close()
    if not built["n_runs"]:
        print("error: nothing matches that selection", file=sys.stderr)
        return 2
    if not args.llm:
        print(built["text"], end="")
        return 0
    if built["refused"]:
        print(f"error: {built['bytes'] // 1024} KB of summary, the limit is "
              f"{scope.MAX_TEXT_BYTES // 1024} KB — narrow the selection",
              file=sys.stderr)
        return 2

    from .coach import generate_critique
    try:
        text, model = generate_critique(system, built["text"], model=args.model)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    doc = critiques.build_scope(
        digest=built["hash"], text=built["text"], selection=selection,
        system=system, model=model, body=text, n_runs=built["n_runs"],
        n_maps=built["n_maps"], first=built["first"], last=built["last"])
    path = critiques.save_scope(out, doc)
    try:
        mirror = index.connect(index.db_path(out))
        try:
            index.sync_scope_critiques(mirror, out)
            mirror.commit()
        finally:
            mirror.close()
    except Exception:
        pass
    print(text)
    print(f"\n— stored: {path} ({model})", file=sys.stderr)
    return 0


def _save_critique(args, text):
    """Store the critique next to the run: out/critiques/<run_id>.json."""
    import os as _os

    from . import critiques, index
    from .coach import load_system_prompt
    from .config import llm_model

    if _os.path.isdir(args.metrics_json):
        print("  ! --save stores one critique per run: pass a single metrics JSON",
              file=sys.stderr)
        return
    try:
        metrics = _load_metrics(args.metrics_json)
    except RuntimeError as exc:
        print(f"  ! not saved: {exc}", file=sys.stderr)
        return
    root = _os.path.dirname(_os.path.abspath(args.metrics_json))
    run_id = index.run_id_for(metrics)
    from .annotations import for_metrics
    doc = critiques.build(metrics, for_metrics(metrics, root),
                          load_system_prompt(args.prompt),
                          args.model or llm_model(), text, run_id=run_id)
    path = critiques.save(root, doc)
    try:
        conn = index.connect(index.db_path(root))
        try:
            index.sync_critiques(conn, root)
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # the sidecar is saved; the mirror can wait
        print(f"  ! index not updated ({exc}) — run `osu-critique index`",
              file=sys.stderr)
    print(f"  saved critique: {path}", file=sys.stderr)


def cmd_profile(args):
    from .profile import fetch_profile
    try:
        p = fetch_profile(args.username, allow_scrape=args.scrape or None)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"== {p['username']} ({p.get('country')}) ==")
    acc, pp, rank = p.get("accuracy_pct"), p.get("pp"), p.get("global_rank")
    acc_s = f"{acc:.2f}" if isinstance(acc, (int, float)) else "?"
    pp_s = f"{pp:.0f}" if isinstance(pp, (int, float)) else "?"
    rank_s = f"{rank:,}" if isinstance(rank, int) else "?"
    print(f"rank #{rank_s}  |  {pp_s}pp  |  acc {acc_s}%")
    print(f"plays {p['play_count']}  |  playtime ~{p['play_time_hours']}h  |  level {p['level']}")
    g = p["grades"]
    print(f"grades: SS {g['ss']}  S {g['s']}  A {g['a']}")
    c = p["counts"]
    print(f"hits: {c['300']}x300 / {c['100']}x100 / {c['50']}x50 / {c['miss']}x miss")
    if p.get("rank_highest"):
        rh = p["rank_highest"]
        print(f"peak rank #{rh.get('rank')} ({rh.get('updated_at', '')[:10]})")
    return 0


def cmd_attempts(args):
    """Cross-attempt structure: which weaknesses hold across plays of one map."""
    import json as _json
    from .coach import _load_metrics_dir
    from .metrics.attempts import build, describe

    target = args.path_or_dir or str(outdir())
    if os.path.isdir(target):
        rows = _load_metrics_dir(target)
        if not rows:
            print(f"error: no *_metrics.json files in {target!r} — run "
                  "`osu-critique batch` or `analyze` first", file=sys.stderr)
            return 2
    else:
        try:
            with open(target) as f:
                rows = [(target, _json.load(f))]
        except (FileNotFoundError, _json.JSONDecodeError) as e:
            print(f"error: cannot read {target!r}: {e}", file=sys.stderr)
            return 2
    block = build(rows, min_n=args.min_n)
    if args.json:
        print(_json.dumps(block, indent=2, default=float))
        return 0
    for line in describe(block, only_repeated=not args.all):
        print(line)
    return 0


def cmd_paths(args):
    """Show every resolved path and whether it exists (debugging aid)."""
    from .config import (cache_dir, lazer_data, lazer_exports, lazer_files,
                         maps_dir, outdir, replays_dir, stable_replays,
                         stable_root, stable_songs)
    paths = [
        ("lazer data", lazer_data()), ("lazer exports", lazer_exports()),
        ("lazer files store", lazer_files()),
        ("stable root", stable_root()), ("stable replays", stable_replays()),
        ("stable songs", stable_songs()),
        ("project replays", replays_dir()), ("project maps", maps_dir()),
        ("cache", cache_dir()), ("outdir", outdir()),
    ]
    for label, p in paths:
        if p is None:
            print(f"  — {label:<16} n/a (Windows only)")
            continue
        mark = "✓" if p.exists() else "—"
        print(f"  {mark} {label:<16} {p}")
    return 0


# --------------------------------------------------------------- setup ------

def _ask(prompt, default=None, secret=False):
    suffix = f" [{default}]" if default else ""
    if secret and sys.stdin.isatty():
        import getpass
        value = getpass.getpass(f"{prompt}{suffix}: ")
    else:
        value = input(f"{prompt}{suffix}: ").strip()
    if value == "":
        return default
    return value


def cmd_setup(args):
    if args.show:
        from .config import load_config
        cfg = load_config()
        masked = {k: ("***" if "key" in k or "secret" in k else v)
                  for k, v in cfg.items()}
        print(json.dumps(masked, indent=2) if cfg else "no config file yet")
        return 0

    from .config import (CONFIG_PATH, outdir, save_config, lazer_data, stable_root)
    print("osu-critique setup — first-time configuration")
    print("Every value is optional; press Enter to accept the [default] or skip.")
    print("Nothing is required for `analyze` / `pair` / `batch` / `report`.\n")

    print("[LLM coach — powers `osu-critique coach`]")
    llm_key = _ask("LLM API key (OpenAI-compatible)", secret=True)
    base_url = _ask("LLM base URL", "https://api.deepseek.com")
    model = _ask("LLM model — enter a custom name if you know yours "
                 "(recommended: deepseek-v4-flash)",
                 "deepseek-v4-flash")

    print("\n[osu! profile — powers `osu-critique profile` via API v2]")
    client_id = _ask("osu! API client id (https://osu.ppy.sh/oauth/clients)", secret=True)
    client_secret = _ask("osu! API client secret", secret=True)
    allow_scrape = _ask("allow unofficial HTML scrape fallback when no API "
                        "credentials are set? (y/N)", "false")
    allow_scrape = "true" if str(allow_scrape).strip().lower() in (
        "y", "yes", "true", "1", "on") else "false"

    print("\n[Paths — where your replays/maps live (auto-detected if empty)]")
    lazer_data_dir = _ask("osu!lazer data dir", str(lazer_data()))
    cfg_extra = {}
    if os.name == "nt":
        stable_root_dir = _ask("osu!stable install dir", str(stable_root()))
        cfg_extra["stable_root"] = stable_root_dir
    outdir_ask = _ask("output dir", str(outdir()))

    cfg = {"llm_key": llm_key, "llm_base_url": base_url, "llm_model": model,
           "osu_client_id": client_id, "osu_client_secret": client_secret,
           "allow_scrape": allow_scrape,
           "lazer_data": lazer_data_dir, **cfg_extra,
           "outdir": outdir_ask}
    cfg = {k: v for k, v in cfg.items() if v is not None}
    path = save_config(cfg)
    print(f"\nsaved to {path} (mode 0600)")
    print("try: osu-critique batch")
    print("     osu-critique report out/<tag>_metrics.json")
    print("     osu-critique coach out/ --all --profile <username>   # cross-run critique")
    return 0


# ------------------------------------------------------------- helpers ----

def _tag_from_replay(replay_path, taken=None):
    """A stable, unique tag for one exported replay.

    The bracket is the difficulty, which is *not* unique: two attempts of the same
    difficulty used to collide, so ``batch`` silently overwrote the first with the
    second and the cross-attempt view saw one play instead of two. The export's
    date stamp (``(2026-09-22_00-33)``) makes the tag per attempt; ``taken`` is a
    last-resort guard for two exports from the same minute.
    """
    import os
    import re
    name = os.path.basename(replay_path)
    m = re.search(r"\[([^\]]+)\]", name)
    base = (re.sub(r"[^A-Za-z0-9_-]+", "_", m.group(1)).strip("_")[:34]
            if m else "run")
    date = re.search(r"(\d{4}-\d{2}-\d{2})[T_ ]?(\d{2})?[-_](\d{2})?", name)
    if date:
        base = f"{base}_{date.group(1)}_{date.group(2) or '00'}{date.group(3) or '00'}"
    base = base[:60]
    if taken is None:
        return base
    tag, n = base, 2
    while tag in taken:
        tag = f"{base}-{n}"
        n += 1
    taken.add(tag)
    return tag


def _aggregate(rows):
    print("\n================ AGGREGATE ================")
    print(f"{'map':<42} {'acc':>6} {'UR':>5} {'mean_ms':>7} {'early':>5} "
          f"{'aim_r':>5} {'miss':>4} {'whiff':>5} {'keysA/B':>7}  flag")
    for m in sorted(rows, key=lambda r: r["accuracy"]):
        h = m["hit_error_ms"]
        flag = "MISMATCH" if m.get("map_version_mismatch") else (
            "*" if m["counts_detected"]["miss"] > m["counts_recorded"]["miss"] + 5 else "")
        print(f"{m['map'][:42]:<42} {m['accuracy'] * 100:5.1f}% {m['ur']:5.1f} "
              f"{h['mean']:+6.1f} {m['early_pct'] * 100:4.0f}% "
              f"{m['aim_px']['mean_norm']:5.2f} {m['counts_recorded']['miss']:4d} "
              f"{m['whiffed_presses']:5d} {m['key_usage']['A']}/{m['key_usage']['B']}  {flag}")


def render_report(metrics, baseline=None):
    """Deterministic, rule-based critique from a metrics dict (no LLM).

    The content is built once in :mod:`osu_critique.report_sections`; this is
    the terminal rendering of it, so the web page and the CLI cannot drift.
    """
    from .report_sections import sections, to_text

    return to_text(metrics, sections(metrics, baseline))


# --------------------------------------------------------------- entry ----

def _apply_memory_guard() -> None:
    """Cap the process address space so a runaway can never freeze the machine.

    A memory-bounded tool must fail fast with MemoryError, not thrash into
    60+ GiB of swap. ``OSU_MEMORY_LIMIT_GB`` overrides the 6 GiB default
    (set 0 to disable). Linux-only; ignored elsewhere."""
    limit_gb = float(os.environ.get("OSU_MEMORY_LIMIT_GB", "6"))
    if not limit_gb or limit_gb <= 0:
        return
    try:
        import resource
        cap = int(limit_gb * 1024 ** 3)
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    except (ImportError, ValueError, OSError):
        pass  # non-Linux or unsupported: leave unguarded


def main(argv=None):
    _apply_memory_guard()
    parser = argparse.ArgumentParser(prog="osu-critique",
                                     description="Data-driven osu! replay analysis.")
    parser.add_argument("--version", action="version", version=f"osu-critique {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="analyze a single replay against its map")
    p.add_argument("replay")
    p.add_argument("map")
    p.add_argument("tag", nargs="?", default="run")
    p.add_argument("--charts", action="store_true", help="also render a PNG chart")
    p.add_argument("--no-objects", action="store_true",
                   help="skip out/<tag>_objects.json (the per-object records)")
    p.add_argument("--no-aim", action="store_true",
                   help="skip the cursor-arrival aim block (metrics.aim_mode)")
    p.add_argument("--no-autopsy", action="store_true",
                   help="skip the miss-autopsy block (metrics.autopsy)")
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("pair", help="resolve lazer replay->map pairs (no analysis)")
    p.set_defaults(func=cmd_pair)

    p = sub.add_parser("batch", help="pair + analyze every exported lazer replay")
    p.add_argument("--charts", action="store_true")
    p.add_argument("--no-objects", action="store_true")
    p.add_argument("--no-aim", action="store_true")
    p.add_argument("--no-autopsy", action="store_true")
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("breakdown", help="how a play breaks down: speed cliff, "
                                         "reversal buckets, cascades, worst ramp")
    p.add_argument("metrics_json", help="a metrics JSON (uses its stored breakdown, "
                                         "or recomputes from the sibling _objects.json)")
    p.add_argument("--json", action="store_true", help="print the block as JSON")
    p.set_defaults(func=cmd_breakdown)

    p = sub.add_parser("stars", help="star rating per beatmap via rosu-pp "
                                      "(optional extra: osu-critique[stars])")
    p.add_argument("path_or_dir", nargs="?", default=None,
                   help="a metrics JSON or a directory of *_metrics.json (default: outdir)")
    p.add_argument("--player", default=None, help="only rate this player's runs")
    p.add_argument("--outdir", default=None,
                   help="where stars_by_md5.json / the md5 index are cached")
    p.add_argument("--lazer-files", default=None, help="override lazer's files/ store")
    p.set_defaults(func=cmd_stars)

    p = sub.add_parser("pp", help="pp + modded attributes per play via rosu-pp "
                                   "(optional extra: osu-critique[stars])")
    p.add_argument("path_or_dir", nargs="?", default=None)
    p.add_argument("--player", default=None)
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_pp)

    p = sub.add_parser("status", help="ranked / leaderboard-only / unranked split "
                                       "over the stored runs (osu! API v2)")
    p.add_argument("path_or_dir", nargs="?", default=None)
    p.add_argument("--player", default=None)
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("report", help="deterministic critique from a metrics JSON (no keys)")
    p.add_argument("metrics_json")
    p.add_argument("--baseline", default=None, help="optional baseline metrics JSON")
    p.add_argument("--history", default=None,
                   help="directory of stored runs to compare against "
                        "(default: the configured output dir)")
    p.add_argument("--no-history", action="store_true",
                   help="skip the rolling-baseline comparison")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("coach", help="AI critique via LLM API (BYO OSU_LLM_KEY)")
    p.add_argument("metrics_json",
                   help="metrics JSON file, or a directory of *_metrics.json "
                        "files (e.g. the output folder from `batch`) for a "
                        "cross-run critique")
    p.add_argument("--all", action="store_true",
                   help="coach every run in the configured output dir")
    p.add_argument("--baseline", default=None, help="optional baseline metrics JSON")
    p.add_argument("--profile", default=None, help="optional osu! username for context")
    p.add_argument("--model", default=None,
                   help="LLM model name to use (overrides config/env); "
                        "default deepseek-v4-flash (the tested/recommended model)")
    p.add_argument("--save", action="store_true",
                   help="store the critique with the run (out/critiques/, one "
                        "metrics JSON only) so the web UI shows it")
    p.add_argument("--prompt", default=None,
                   help="custom critique-framework prompt file (overrides built-in)")
    p.set_defaults(func=cmd_coach)

    p = sub.add_parser("critique", help="a critique of a *selection*: replays, "
                                        "whole maps, a date range, or any mix")
    p.add_argument("--runs", default="", help="comma-separated run ids")
    p.add_argument("--maps", default="", help="comma-separated beatmap md5s (every attempt)")
    p.add_argument("--since", default=None,
                   help="today | session | 7d | 30d | YYYY-MM-DD (played_at, not export time)")
    p.add_argument("--until", default=None, help="YYYY-MM-DD, inclusive")
    p.add_argument("--llm", action="store_true",
                   help="call the model too, and store the answer with the summary it read")
    p.add_argument("--model", default=None, help="LLM model (overrides config/env)")
    p.add_argument("--prompt", default=None, help="custom scope-framework prompt file")
    p.set_defaults(func=cmd_critique)

    p = sub.add_parser("prompt", help="print the critique-framework prompt (bring-your-own-AI)")
    p.add_argument("metrics_json", nargs="?", default=None,
                   help="optional metrics JSON or a folder of *_metrics.json: "
                        "print a full ready-to-paste prompt")
    p.add_argument("--baseline", default=None, help="optional baseline metrics JSON")
    p.add_argument("--profile", default=None, help="optional osu! username for context")
    p.add_argument("--scrape", action="store_true",
                   help="allow the unofficial HTML profile fallback")
    p.add_argument("--save", action="store_true",
                   help="store the critique with the run (out/critiques/, one "
                        "metrics JSON only) so the web UI shows it")
    p.add_argument("--prompt", default=None, help="custom prompt file (overrides built-in)")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("profile", help="fetch an osu! profile (API v2, or HTML fallback with --scrape)")
    p.add_argument("username")
    p.add_argument("--scrape", action="store_true",
                   help="allow the unofficial HTML fallback (requires no API credentials; "
                        "prefer the official API v2)")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("setup", help="first-time configuration wizard (paths + optional keys)")
    p.add_argument("--show", action="store_true", help="show the effective config (masked)")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("attempts", help="cross-attempt structure: stable weaknesses "
                                        "vs one-off noise (same map, several plays)")
    p.add_argument("path_or_dir", nargs="?", default=None,
                   help="a metrics JSON or a directory of *_metrics.json (default: outdir)")
    p.add_argument("--min-n", type=int, default=None,
                   help="objects a bucket needs in EVERY attempt to be compared")
    p.add_argument("--all", action="store_true",
                   help="also list maps with a single attempt")
    p.add_argument("--json", action="store_true", help="print the block as JSON")
    p.set_defaults(func=cmd_attempts)

    p = sub.add_parser("paths", help="show resolved replay/map/output paths (auto-detected)")
    p.set_defaults(func=cmd_paths)

    p = sub.add_parser("index", help="build / refresh the SQLite index of out/ "
                                     "(derived; safe to delete and rebuild)")
    p.add_argument("--rebuild", action="store_true",
                   help="drop every row and re-read all artifacts")
    p.add_argument("--check", action="store_true",
                   help="report drift between out/ and the index; write nothing")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--quiet", action="store_true", help="no progress meter")
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("serve", help="run the local web frontend "
                                     "(needs the [web] extra)")
    p.add_argument("--host", default=None,
                   help="bind address (default: web.host, else 0.0.0.0)")
    p.add_argument("--port", type=int, default=None,
                   help="port (default: web.port, else 8765)")
    p.add_argument("--no-index", action="store_true",
                   help="do not sweep the index on boot")
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("annotate", help="human annotations (map- or run-scoped) "
                                        "that the coach prompt reads")
    sub_ann = p.add_subparsers(dest="action", required=True)
    a = sub_ann.add_parser("add", help="add a note")
    a.add_argument("text", nargs="+", help="the note body")
    a.add_argument("--map", required=True, metavar="MD5",
                   help="beatmap md5 (the folder under out/annotations/)")
    a.add_argument("--run", metavar="REPLAY_MD5", default=None,
                   help="scope the note to one attempt")
    a.add_argument("--t", default=None, metavar="TIME",
                   help="timestamp in map time: 134.312 or 2:14.312")
    a.add_argument("--tag", action="append", default=[],
                   help="tag (repeatable)")
    a.add_argument("--outdir", default=None)
    a.set_defaults(func=cmd_annotate)

    a = sub_ann.add_parser("list", help="list notes")
    a.add_argument("--map", default=None, metavar="MD5")
    a.add_argument("--run", default=None, metavar="REPLAY_MD5")
    a.add_argument("--json", action="store_true")
    a.add_argument("--outdir", default=None)
    a.set_defaults(func=cmd_annotate)

    a = sub_ann.add_parser("rm", help="remove a note by id")
    a.add_argument("id")
    a.add_argument("--map", default=None, metavar="MD5",
                   help="skip the search for the owning sidecar")
    a.add_argument("--outdir", default=None)
    a.set_defaults(func=cmd_annotate)

    p = sub.add_parser("export", help="opt-in replay export from osu!lazer's "
                                     "database (needs BeatmapExporter; disabled "
                                     "unless export.enabled is true)")
    p.add_argument("--install", action="store_true",
                   help="download the pinned BeatmapExporter for this platform "
                        "(sha256-verified) into ~/.local/share/osu-critique/bin")
    p.add_argument("--force", action="store_true", help="re-download even if present")
    p.add_argument("--run", action="store_true", help="actually export")
    p.add_argument("--status", default=None, metavar="LIST",
                   help="comma-separated status filter (ranked,loved,...); "
                        "default: no filter, export everything")
    p.add_argument("--prune-player", default=None, metavar="NAME",
                   help="delete exported replays whose filename does not start "
                        "with NAME (the Realm also holds other players' replays)")
    p.add_argument("--timeout", type=float, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("digest", help="what happened since your last digest: "
                                     "ingest new replays and summarise (no LLM)")
    p.add_argument("--since", default=None, metavar="TIME",
                   help="ISO timestamp (default: the previous digest)")
    p.add_argument("--no-ingest", action="store_true",
                   help="summarise only; do not analyse new exported replays")
    p.add_argument("--no-export", action="store_true",
                   help="do not pull replays out of osu! even if export.enabled is true")
    p.add_argument("--stdout", action="store_true",
                   help="print only; do not write out/digests/ or move the marker")
    p.add_argument("--json", action="store_true")
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_digest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
