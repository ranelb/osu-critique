"""osu-critique command line interface.

Subcommands:
  analyze <replay.osr> <map.osu> [tag]   analyze a single replay (zero keys)
  pair              resolve replay->map pairs (no analysis)
  batch             pair + analyze every available replay + aggregate
  paths             show resolved (auto-detected) paths
  prompt  [metrics] [--baseline] [--profile]   print the critique prompt (BYO AI)
  report  <metrics.json> [--baseline]    deterministic critique (no LLM, no keys)
  coach   <metrics.json> [--baseline] [--profile]   AI critique (BYO OSU_LLM_KEY)
  profile <username>                     fetch osu! profile (BYO osu API creds)
  setup   [--show]                       first-time configuration wizard
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .config import outdir
from .io import pairing
from .report import analyze, console_summary


# ------------------------------------------------------------- commands ----


def cmd_analyze(args):
    metrics = analyze(args.replay, args.map, tag=args.tag or "run",
                      do_charts=args.charts, outdir=args.outdir)
    console_summary(metrics)
    return 0


def cmd_pair(args):
    for source, rp, mp in pairing.pair_all():
        print(f"  [{source:7s}] {rp}  ->  {mp}")
    return 0


def cmd_batch(args):
    pairs = pairing.pair_all()
    print(f"\npaired {len(pairs)} replay+map sets\n")

    rows = []
    for source, rp, mp in pairs:
        tag = _tag_from_replay(rp)
        metrics = analyze(rp, mp, tag=tag, do_charts=args.charts,
                          outdir=args.outdir, console=False)
        console_summary(metrics)
        rows.append(metrics)
        print()

    _aggregate(rows)
    return 0


def cmd_prompt(args):
    """Print the critique-framework prompt; with a metrics JSON, print a full
    ready-to-paste prompt (system + data) for use with any AI of your choice."""
    from .coach import build_user_message, load_system_prompt
    system = load_system_prompt(args.prompt)
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
        print(system)
        print("\n\n" + build_user_message(metrics, baseline, profile))
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
    print(render_report(metrics, baseline))
    return 0


def cmd_coach(args):
    from .coach import coach as run_coach
    profile = None
    if args.profile:
        from .profile import fetch_profile
        profile = fetch_profile(args.profile)
        print(f"profile: {profile.get('username')} "
              f"#{profile.get('global_rank')} · {profile.get('pp')}pp · "
              f"{profile.get('play_time_hours')}h", file=sys.stderr)
    try:
        critique = run_coach(args.metrics_json, args.baseline, profile,
                             model=args.model, prompt_file=args.prompt)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(critique)
    return 0


def cmd_profile(args):
    from .profile import fetch_profile
    try:
        p = fetch_profile(args.username, allow_scrape=args.scrape or None)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"== {p['username']} ({p.get('country')}) ==")
    print(f"rank #{p['global_rank']}  |  {p['pp']}pp  |  acc {p['accuracy_pct']}%")
    print(f"plays {p['play_count']}  |  playtime ~{p['play_time_hours']}h  |  level {p['level']}")
    g = p["grades"]
    print(f"grades: SS {g['ss']}  S {g['s']}  A {g['a']}")
    c = p["counts"]
    print(f"hits: {c['300']}x300 / {c['100']}x100 / {c['50']}x50 / {c['miss']}x miss")
    if p.get("rank_highest"):
        rh = p["rank_highest"]
        print(f"peak rank #{rh.get('rank')} ({rh.get('updated_at', '')[:10]})")
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
    print("     osu-critique coach out/<tag>_metrics.json [--profile <username>]")
    return 0


# ------------------------------------------------------------- helpers ----

def _tag_from_replay(replay_path):
    import os
    import re
    name = os.path.basename(replay_path)
    m = re.search(r"\[([^\]]+)\]", name)
    if m:
        return re.sub(r"[^A-Za-z0-9_-]+", "_", m.group(1)).strip("_")[:40]
    return "run"


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
    """Deterministic, rule-based critique from a metrics dict (no LLM)."""
    h = metrics["hit_error_ms"]
    ur = metrics["ur"]
    aim = metrics["aim_px"]
    b = baseline or {}
    b_ur = b.get("ur")
    b_aim = b.get("aim_px", {}).get("mean_norm") if isinstance(b.get("aim_px"), dict) else None

    def ur_verdict(v):
        if v is None:
            return "n/a"
        if v < 120:
            return "excellent"
        if v < 180:
            return "good"
        if v < 250:
            return "inconsistent"
        return "timing breakdown"

    def aim_verdict(v):
        if v is None:
            return "n/a"
        if v < 0.30:
            return "strong"
        if v < 0.45:
            return "good"
        if v < 0.60:
            return "acceptable"
        return "aim struggling"

    lines = [f"# Report: {metrics['map']}", "",
             f"- Accuracy {metrics['accuracy'] * 100:.1f}% | UR {ur:.1f} ({ur_verdict(ur)}) "
             f"| {metrics['counts_recorded']['300']}x300 / "
             f"{metrics['counts_recorded']['100']}x100 / "
             f"{metrics['counts_recorded']['50']}x50 / "
             f"{metrics['counts_recorded']['miss']}x miss | max combo {metrics['max_combo']}"]
    if metrics.get("failed_play"):
        lines.append("- NOTE: this was a failed play (ended before the map finished).")
    if metrics.get("map_version_mismatch"):
        lines.append("- NOTE: replay/map timing mismatch detected; analysis unreliable past the replay end.")
    lines += ["", "## Timing",
              f"- mean hit error {h['mean']:+.1f}ms ({metrics['early_pct'] * 100:.0f}% early), "
              f"std {h['std']:.1f}ms",
              f"- vs baseline: UR {ur_verdict(ur)}" + (f" (baseline {b_ur:.0f})" if b_ur else ""),
              f"- |bias| > 6ms with consistent sign -> consider an offset test."]
    lines += ["", "## Aim",
              f"- mean aim error {aim['mean_norm']:.2f}r ({aim_verdict(aim['mean_norm'])})"
              + (f" vs baseline {b_aim:.2f}r" if b_aim else ""), ""]

    pat = metrics["patterns"]
    if pat:
        lines.append("## Patterns (miss rate by spacing)")
        for p, d in sorted(pat.items(), key=lambda kv: -kv[1]["n"]):
            lines.append(f"- {p:8s} n={d['n']:4d} miss={d['miss']:3d} "
                         f"({d['miss_rate'] * 100:.1f}%) "
                         f"err={d['mean_err'] and round(d['mean_err'], 1)}ms "
                         f"std={d['std_err'] and round(d['std_err'], 1)}ms")
        worst = max((kv for kv in pat.items() if kv[0] != "first" and kv[1]["miss"] > 0),
                    key=lambda kv: kv[1]["miss"], default=None)
        if worst:
            lines += ["", f"**Primary target: `{worst[0]}`** "
                          f"({worst[1]['miss']} misses, {worst[1]['miss_rate'] * 100:.1f}% rate)."]
        else:
            lines += ["", "**No pattern stands out as a weakness — clean run.**"]

    segs = metrics["streams"]["segments"]
    if segs:
        lines += ["", "## Streams", f"- {len(segs)} segments, "
                                    f"{sum(s['n'] for s in segs)} objects, "
                                    f"{sum(s['miss'] for s in segs)} misses"]
        for s in sorted(segs, key=lambda s: -(s["std_err"] or 0))[:3]:
            lines.append(f"- t={s['t_start'] / 1000:.0f}s-{s['t_end'] / 1000:.0f}s "
                         f"n={s['n']} miss={s['miss']} std={s['std_err'] and round(s['std_err'], 1)}ms "
                         f"alt={s['alt_ratio'] * 100:.0f}%")

    tap = metrics["tapping"]
    lines += ["", "## Tapping",
              f"- alternation {tap['alt_ratio'] * 100:.0f}% (good > 90%), "
              f"same-key adjacencies {tap['same_key_pct'] * 100:.1f}%",
              f"- keys {metrics['key_usage']} | whiffed presses {metrics['whiffed_presses']} "
              f"(rate {metrics['whiffed_presses'] / max(1, tap['n']):.1%})"]
    return "\n".join(lines)


# --------------------------------------------------------------- entry ----

def main(argv=None):
    parser = argparse.ArgumentParser(prog="osu-critique",
                                     description="Data-driven osu! replay analysis.")
    parser.add_argument("--version", action="version", version=f"osu-critique {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="analyze a single replay against its map")
    p.add_argument("replay")
    p.add_argument("map")
    p.add_argument("tag", nargs="?", default="run")
    p.add_argument("--charts", action="store_true", help="also render a PNG chart")
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("pair", help="resolve lazer replay->map pairs (no analysis)")
    p.set_defaults(func=cmd_pair)

    p = sub.add_parser("batch", help="pair + analyze every exported lazer replay")
    p.add_argument("--charts", action="store_true")
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("report", help="deterministic critique from a metrics JSON (no keys)")
    p.add_argument("metrics_json")
    p.add_argument("--baseline", default=None, help="optional baseline metrics JSON")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("coach", help="AI critique via LLM API (BYO OSU_LLM_KEY)")
    p.add_argument("metrics_json")
    p.add_argument("--baseline", default=None, help="optional baseline metrics JSON")
    p.add_argument("--profile", default=None, help="optional osu! username for context")
    p.add_argument("--model", default=None,
                   help="LLM model name to use (overrides config/env); "
                        "default deepseek-v4-flash (the tested/recommended model)")
    p.add_argument("--prompt", default=None,
                   help="custom critique-framework prompt file (overrides built-in)")
    p.set_defaults(func=cmd_coach)

    p = sub.add_parser("prompt", help="print the critique-framework prompt (bring-your-own-AI)")
    p.add_argument("metrics_json", nargs="?", default=None,
                   help="optional metrics JSON: print a full ready-to-paste prompt")
    p.add_argument("--baseline", default=None, help="optional baseline metrics JSON")
    p.add_argument("--profile", default=None, help="optional osu! username for context")
    p.add_argument("--scrape", action="store_true",
                   help="allow the unofficial HTML profile fallback")
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

    p = sub.add_parser("paths", help="show resolved replay/map/output paths (auto-detected)")
    p.set_defaults(func=cmd_paths)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
