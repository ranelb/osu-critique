"""Cursor autopsy for one replay: the numbers and the figures, in one command.

This used to be the reference implementation of the whole method. It is now a
thin printer over the pipeline, because the two blocks it pioneered are part of
``analyze`` itself:

- **aim** (``metrics["aim_mode"]``, ``docs/aim.md``) — distance at the note,
  closest approach and when it peaks, reached-not-on-time, the along/lateral
  split, the speed-conditioned ceiling curve.
- **miss autopsy** (``metrics["autopsy"]``, ``docs/autopsy.md``) — 5-note shape
  classes with n-gated off-300 rates, the press-time arrival margin, press vs
  arrival timing, per-leg heading error and path efficiency, mid-travel
  ("stutter") presses and the misses themselves.

Both are printed here in full and drawn as ``<tag>_aim.png`` (six panels) and
``<tag>_windows.png`` (the worst arrival stretches). The only thing this script
adds is the worst-arrival table. Use it for one replay; use ``osu-critique
analyze`` when you want the JSON and the records.

    python scripts/autopsy.py <replay.osr> [--map MAP] [--out DIR] [--tag NAME] [--no-plots]

Works for normal replays and for Relax (RX) ones: under RX the game taps, so the
tap sections are reported as unavailable and the cursor sections carry the play.
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np  # noqa: E402

from osu_critique.io import pairing  # noqa: E402
from osu_critique.io.beatmap import build_objects, circle_radius, load_beatmap  # noqa: E402
from osu_critique.io.replay import build_frames, load_replay  # noqa: E402
from osu_critique.metrics.aim import build_aim, describe as describe_aim  # noqa: E402
from osu_critique.metrics.autopsy import describe as describe_autopsy  # noqa: E402
from osu_critique.report import analyze  # noqa: E402


def resolve_map(replay_path, explicit=None):
    if explicit:
        return explicit
    base = os.path.basename(replay_path)
    for _src, rp, mp in pairing.pair_all():
        if os.path.basename(rp) == base:
            return mp
    raise SystemExit(f"no map paired with {base!r} - pass --map")


def main(argv=None):
    ap = argparse.ArgumentParser(description="cursor autopsy for one replay")
    ap.add_argument("replay")
    ap.add_argument("--map", default=None, help="beatmap .osu (default: auto-pair by md5)")
    ap.add_argument("--out", default="out/autopsy", help="where the figures go")
    ap.add_argument("--tag", default=None, help="name for the output files")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args(argv)

    tag = args.tag or os.path.splitext(os.path.basename(args.replay))[0][:40].strip().replace(" ", "_")
    map_path = resolve_map(args.replay, args.map)

    metrics = analyze(args.replay, map_path, tag=tag, outdir=args.out,
                      do_charts=not args.no_plots, console=False,
                      write_objects=False)
    trust = metrics["trust"]
    diff = metrics["difficulty"]
    print(f"MAP  {metrics['map']}  [{metrics['mod_string']}]  md5 {metrics['beatmap_md5'][:10]}")
    print(f"     {metrics['n_objects']} objects | CS {diff['CS']:.1f} AR {diff['AR']:.1f} "
          f"OD {diff['OD']:.1f} | radius {metrics['spacing_radius']:.1f}px | "
          f"windows {metrics['windows_ms']['300']:.0f}/{metrics['windows_ms']['100']:.0f}/"
          f"{metrics['windows_ms']['50']:.0f} ms | time scale {metrics['time_scale']}")
    print(f"     recorded {metrics['counts_recorded']} | detected {metrics['counts_detected']} | "
          f"trustworthy {trust['trustworthy']} | {trust['notes'] or 'within tolerance'}")
    if metrics["aim_mode"] and metrics["aim_mode"]["is_relax"]:
        print("     RELAX: taps are the game's, so only the cursor sections below mean anything")

    print()
    for line in describe_aim(metrics["aim_mode"]):
        print(line)
    print()
    for line in describe_autopsy(metrics["autopsy"]):
        print(line)

    # the per-object worst arrivals (everything else is already in the blocks)
    r = load_replay(args.replay)
    bm = load_beatmap(map_path)
    r.beatmap = bm
    frames = build_frames(r)
    times = np.array([f[0] for f in frames])
    radius = circle_radius(bm.cs())
    objs = build_objects(bm, metrics["time_scale"],
                         hard_rock=metrics["mods"].get("HR", False))
    _block, rows = build_aim(objs, frames, times, radius,
                             is_relax=bool(metrics["aim_mode"] and metrics["aim_mode"]["is_relax"]))
    print("\nWORST arrivals (distance at the note instant)")
    for x in sorted(rows, key=lambda x: -x["d"])[:8]:
        print(f"  #{x['i']:4d} t={x['t'] / 1000:6.1f}s {x['kind']:6s} {x['d']:5.2f}r | "
              f"closest {x['dmin']:4.2f}r at {x['peak_off']:+4.0f}ms | "
              f"speed {(x['speed'] or 0):4.2f}px/ms gap {(x['gap_r'] or 0):4.1f}r")

    if not args.no_plots:
        print(f"\nfigures: {os.path.join(args.out, tag)}_aim.png")
        print(f"         {os.path.join(args.out, tag)}_windows.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
