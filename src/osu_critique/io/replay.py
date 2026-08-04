"""Replay (.osr) loading and frame extraction."""
from __future__ import annotations

import bisect

import slider


def load_replay(replay_path):
    """Load an .osr replay without attaching a beatmap (caller sets .beatmap)."""
    return slider.Replay.from_path(replay_path, retrieve_beatmap=False)


def build_frames(r):
    """list of (time_ms, x, y, keyA_down, keyB_down); keyA = K1|M1, keyB = K2|M2.

    Sorted by time: some export tools append out-of-order
    trailing frames (e.g. a pen-reset frame with an earlier timestamp), which
    would break press detection and cursor interpolation if left unsorted.
    """
    frames = []
    for a in r.actions:
        t = a.offset.total_seconds() * 1000.0
        frames.append((t, a.position.x, a.position.y,
                       bool(a.key1 or a.mouse1), bool(a.key2 or a.mouse2)))
    frames.sort(key=lambda f: f[0])
    return frames


def find_presses(frames):
    """Detect rising edges on either tap button -> list of (time_ms, 'A'|'B')."""
    presses = []
    prev_a = prev_b = False
    for t, x, y, a_down, b_down in frames:
        if a_down and not prev_a:
            presses.append((t, "A"))
        if b_down and not prev_b:
            presses.append((t, "B"))
        prev_a, prev_b = a_down, b_down
    return presses


def cursor_at(frames, times, t):
    """Linear-interpolated (x, y) at time t."""
    i = bisect.bisect_right(times, t)
    if i == 0:
        return frames[0][1], frames[0][2]
    if i >= len(frames):
        return frames[-1][1], frames[-1][2]
    t0, x0, y0, *_ = frames[i - 1]
    t1, x1, y1, *_ = frames[i]
    dt = t1 - t0
    if dt <= 0:
        return x1, y1
    f = (t - t0) / dt
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
