"""osu-critique command line interface.

Subcommands:
  analyze <replay.osr> <map.osu> [tag]   analyze a single replay (zero keys)
  pair    [--source danser|lazer|all]    resolve replay->map pairs (no analysis)
  batch   [--source danser|lazer|all]    pair + analyze everything + aggregate
  report  <metrics.json> [--baseline]    deterministic critique (no LLM, no keys)
  coach   (planned, Phase C: BYO LLM key)
  profile (planned, Phase C: BYO osu! API credentials)
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .config import DEFAULT_OUTDIR
from .io import pairing
from .report import analyze, console_summary


# ------------------------------------------------------------- commands ----

def cmd_analyze(args):
    metrics = analyze(args.replay, args.map, tag=args.tag or "run",
                      do_charts=args.charts, outdir=args.outdir)
    console_summary(metrics)
    return 0


def cmd_pair(args):
    if args.source in ("danser", "all"):
        print("== danser ==")
        for rp, mp in pairing.pair_danser():
            print(f"  {rp}  ->  {mp}")
    if args.source in ("lazer", "all"):
        print("== lazer ==")
        for rp, mp in pairing.pair_lazer():
            print(f"  {rp}  ->  {mp}")
    return 0


def cmd_batch(args):
    pairs = []
    if args.source in ("danser", "all"):
        pairs += pairing.pair_danser()
    if args.source in ("lazer", "all"):
        pairs += pairing.pair_lazer()
    print(f"\npaired {len(pairs)} replay+map sets\n")

    rows = []
    for rp, mp in pairs:
        tag = _tag_from_replay(rp)
        metrics = analyze(rp, mp, tag=tag, do_charts=args.charts,
                          outdir=args.outdir, console=False)
        console_summary(metrics)
        rows.append(metrics)
        print()

    _aggregate(rows)
    return 0


def cmd_report(args):
    with open(args.metrics_json) as f:
        metrics = json.load(f)
    baseline = None
    if args.baseline:
        with open(args.baseline) as f:
            baseline = json.load(f)
    print(render_report(metrics, baseline))
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

    p = sub.add_parser("pair", help="resolve replay->map pairs (no analysis)")
    p.add_argument("--source", choices=["danser", "lazer", "all"], default="all")
    p.set_defaults(func=cmd_pair)

    p = sub.add_parser("batch", help="pair + analyze every replay in the configured folders")
    p.add_argument("--source", choices=["danser", "lazer", "all"], default="all")
    p.add_argument("--charts", action="store_true")
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("report", help="deterministic critique from a metrics JSON (no keys)")
    p.add_argument("metrics_json")
    p.add_argument("--baseline", default=None, help="optional baseline metrics JSON")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
