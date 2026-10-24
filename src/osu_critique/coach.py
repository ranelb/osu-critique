"""AI critique (bring-your-own-key): one LLM API call from a metrics JSON.

No agent loop, no harness: everything is precomputed into the metrics JSON,
so the critique is a single chat-completions request. OpenAI-compatible
endpoints only (works with OpenAI, OpenRouter, local servers, etc.).

Environment:
    OSU_LLM_KEY        API key (required)
    OSU_LLM_BASE_URL   default https://api.deepseek.com
    OSU_LLM_MODEL      default deepseek-v4-flash
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

SYSTEM_PROMPT = """You are an osu! gameplay analyst. The user gives you a metrics JSON from a replay
analysis pipeline (per-object hit/aim error derived from an .osr + .osu pair),
optionally a baseline JSON (compare only like with like: same map, or the same
difficulty band) and optionally their osu! profile stats.

Critique framework - use the numbers, don't invent others:

- Trust first: read metrics["trust"]. If trustworthy is false, or abs_delta_total
  is large relative to judged, say that in your first line and mark every
  per-pattern and miss number as approximate; trust.notes says why (failed play,
  map_version_mismatch, relax). Never present untrusted numbers as fact.
- Time base first: metrics.time_base says whether the replay's mod flag and its
  frames disagree (overridden). Every ms in the metrics is the *frames'* base
  unless it says "player"; time_base.windows_ms_player is the same windows in the
  clock the player actually felt, and metrics.profile is already player time.
  Never compare an ms from one base with one from the other: when
  rows_to_player != 1 the same hit window is two different numbers, and the quote
  must say which.
- Timing: mean hit error (early/late sign), std, UR = std*10, and
  ur_pct_of_300_window - the spread as a share of the OD 300-window
  (windows_ms). Under ~50% is tight for a human; near 100% means the spread
  covers the whole 300 window. |bias| > 6ms with a consistent sign -> suggest a
  universal offset test.
- Aim, two clocks. Press-time aim (aim_px.mean_norm, aim_vs_speed) samples the
  cursor only at the tap. metrics.aim_mode samples the cursor path itself: the
  distance at the note instant (distance_at_note_r), the closest approach within
  the window (closest_approach_r), when that approach peaks (peak_offset_ms -
  late means the cursor arrives after the note), the share reached but not on
  time (reached_not_on_time), the along/lateral split (error_shape: short vs
  past, and sideways) and the ceiling curve (distance at the note binned by the
  cursor speed the jump demands). A large aim_mode distance with a small
  closest_approach_r is an arrival-timing problem, not a precision one - say so.
  aim_vs_speed gives the press-time slope in radii per px/ms. Under Relax (RX)
  there are no taps, so aim_mode is the only aim data that means anything.
- Whiffed presses: whiffs.mash / off_target / slider_head / lost / after_end.
  Only the off_target share is the cursor not arriving in time; mash is a press
  with nothing in the window; slider_head is a limit of the head-only slider
  model. Do not call whiffs "rushing" without checking which cause dominates.
- Slider bodies (metrics.sliders): n / miss / cut and cut_pct (how often the
  cursor left the follow circle), tick_missed_pct, tail_off (dropped end),
  off_pct_median. Turn them into coaching ("you cut 25% of the sliders"), but do
  not treat them as judgements: measured on these replays the game still counts a
  cut slider as a 300, so cuts cost combo and flow, not accuracy points.
- Patterns: the spacing buckets (dense/stream/jump/bigjump) are coarse - one
  bucket mixes a 1/2 jump with a 1/6 one. Prefer the shape classes
  (metrics.autopsy.shapes) and the per-family composition: they are built from
  the per-object records (out/<tag>_objects.json: snap in quarter-beats,
  spacing_r, angle_deg, strain_aim, strain_speed) and require >= 20 objects in a
  bucket before calling it a weakness (each entry carries n and reported).
  Strain deciles ("what happens on the hardest 10% of objects") are the
  difficulty-normalised form.
- Miss autopsy (metrics["autopsy"]) answers "why *these* notes": shapes (5-note
  window classes - near-reversal chain / cornered (box) / flow / mixed) with
  n-gated off-300 rates and the arrival distance per class; arrival_margin_r
  (the press-time distance from the centre - the "living on the rim" tail);
  press_vs_arrival_ms (press offset minus closest-approach offset; negative =
  the button went down while the cursor was still travelling); legs (heading
  error between consecutive notes and path efficiency - both clean means the
  problem is timing or speed, not reading or path-finding); stutter (presses
  made mid-travel); and misses (each miss with its nearest press, its distance
  at the note instant and the local geometry). Use the shape contrast: a
  weakness in one class and not another names what to practise.
- Map profile (metrics["profile"]) describes what the map asked for, not how you
  played: rate (effective BPM, real note gaps in ms, and the tightest gap as a
  multiple of the 300-window), composition (families named kind + divisor +
  spacing with n-gated hit rates), stamina (notes/s, seconds above 6 n/s,
  longest run, breaks), chains (runs with a steady gap, with the hit rate by
  position 1-4 / 5-8 / 9-12 / 13+), timing_by_family (signed bias per family)
  and context (what preceded each object). Quote the real ms gap next to any
  rhythm claim: "1/4 snap" means nothing without it, and "1/8" in one map's
  map-time is another map's 1/2.
- Streams (metrics.streams): runs of sustained notes found by *rhythm* (steady
  gap, <= 250 ms) and *velocity continuity* (required speed spacing/dt steady
  within 40%) - any kind, sliders included - not by spacing, so wide but tight
  patterns count and slow small-spacing filler does not. Each segment reports what
  the material was (gap_ms, notes_per_s, velocity_r_ms, kinds) plus std (ms) and
  alternation. std > 30 ms or alternation < 90% = rhythm collapse under sustained
  tapping; long segments failing while short ones hold = a sustain problem. Quote
  the rate and the material, not just "streams".
- How it breaks down (metrics["breakdown"]): the mechanism under the misses.
  speed_bins is miss rate per *required cursor speed* (recomputed from
  geometry, so a bin with no misses is real), knee/cliff are the safe speed and
  where misses explode; reversal is sharp turns (>=150deg) split at 6r spacing
  vs flow; cascades are runs of consecutive misses (accumulation, not isolated
  whiffs); ramp is the missiest 28-note window with its spacing/speed range. A
  cliff with a low knee is a capacity problem; misses at every speed are a
  reading/consistency one - say which.
- Value, when joined: metrics.sr (base NM rating and effective rating with the
  play's mods), metrics.pp ({pp, stars, aim, speed, mods}) and metrics.rank_status
  (ranked/approved = pp-eligible, qualified/loved = leaderboard-only,
  pending/wip/graveyard = unranked). Use them for context and to say whether a
  play was worth pp; never compare raw pp across different SR without saying so.
- Quarters: misses clustering in one quarter means section difficulty; std
  degrading toward Q4 looks like fatigue, but a map that ramps in difficulty
  looks identical - check the strain fields before blaming fatigue.
- Tapping: alternation ratio > 90% is good; high same-key adjacency = double-taps
  under pressure; key balance A vs B.
- Flags: failed_play = the run ended early (only critique the played portion and
  say so); map_version_mismatch = replay/map timing mismatch, unreliable past the
  replay end; relax (RX) or autopilot = the game hit from cursor position, so
  press-time aim and timing are the game's - judge aim and timing from aim_mode
  (cursor arrival) instead, and ignore whiffs/tapping.

Output: a concise markdown critique with (1) a verdict summary, (2) strengths,
(3) weaknesses ranked by impact, (4) 3-5 specific practice recommendations tied to
the actual numbers, (5) what the data cannot show. Be honest and direct; no fluff,
no generic advice. If a baseline is provided, flag improvement or regression
explicitly. If the player profile is provided, use it for context (hours, rank,
playstyle) but never let it override the play data."""


def load_system_prompt(prompt_file=None) -> str:
    """The critique framework prompt; a custom file overrides the built-in."""
    if prompt_file:
        with open(prompt_file) as f:
            return f.read().strip()
    return SYSTEM_PROMPT


def _call_chat(system: str, user: str, key: str, base_url: str, model: str,
               timeout: float | None = None, on_delta=None) -> str:
    """Single chat-completions call with a TOTAL deadline (not per-read).

    urllib's ``timeout`` is per socket operation — a stalled or trickling
    response can hang indefinitely. We instead read the body in a loop and
    enforce a wall-clock deadline, so a slow model fails cleanly instead of
    appearing frozen."""
    total = timeout if timeout is not None else float(
        os.environ.get("OSU_LLM_TIMEOUT", "300"))
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.4,
        "stream": True,
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Accept": "text/event-stream",
                 "Authorization": f"Bearer {key}"},
    )
    import time
    deadline = time.monotonic() + total
    sock_timeout = min(30.0, total)
    print(f"  waiting for LLM response (deadline {total:.0f}s)...",
          file=sys.stderr)
    try:
        with urllib.request.urlopen(req, timeout=sock_timeout) as resp:
            return _read_stream(resp, deadline, total, on_delta=on_delta)
    except urllib.error.HTTPError as e:
        # some OpenAI-compatible endpoints reject "stream": fall back once
        if e.code in (400, 404, 422) and b"stream" in (e.read() or b"").lower():
            body2 = body.replace(b'"stream": true', b'"stream": false')
            req2 = urllib.request.Request(
                base_url.rstrip("/") + "/chat/completions", data=body2,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req2, timeout=sock_timeout) as resp2:
                return _read_stream(resp2, deadline, total, stream=False,
                                    on_delta=on_delta)
        raise


def _read_stream(resp, deadline, total, stream=True, on_delta=None):
    """Read a chat-completions response. Streaming mode prints tokens live and
    returns the assembled text; non-streaming returns the parsed content."""
    import time
    max_buf = 16 * 1024 * 1024      # a single SSE line bigger than 16 MiB is a runaway
    max_total = 64 * 1024 * 1024    # a critique bigger than 64 MiB is a runaway
    buf = b""
    pieces = []
    while True:
        if time.monotonic() >= deadline:
            if stream and pieces:
                raise RuntimeError(
                    f"LLM response timed out after {total:.0f}s (got partial "
                    f"output above) — set OSU_LLM_TIMEOUT higher or coach fewer runs.")
            raise RuntimeError(
                f"LLM response did not finish within {total:.0f}s — the model "
                "may be overloaded or the prompt too large. Retry, set "
                "OSU_LLM_TIMEOUT higher, or coach fewer runs.")
        try:
            chunk = resp.read(64)    # tiny amt: http.client's chunked reader
                                     # accumulates to amt then returns, so a big
                                     # amt buffers the whole stream and kills
                                     # live output; ~64B ≈ one SSE event per gulp
        except TimeoutError:
            continue  # socket-level stall; the deadline loop decides
        if not chunk:
            break
        if stream:
            buf += chunk
            if len(buf) > max_buf:
                raise RuntimeError(f"LLM stream exceeded a single {max_buf//2**20} MiB "
                                   "line — endpoint behaving abnormally")
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                _consume_sse(line, pieces, on_delta)
            if sum(len(p) for p in pieces) > max_total:
                raise RuntimeError(f"LLM response exceeded {max_total//2**20} MiB — "
                                   "aborting (endpoint runaway?)")
        else:
            buf += chunk
    if stream:
        if buf.strip():
            _consume_sse(buf, pieces, on_delta)
        return "".join(pieces)
    data = json.loads(buf.decode())
    return data["choices"][0]["message"]["content"]


def _consume_sse(line: bytes, pieces: list[str], on_delta=None):
    """Parse one SSE line: ``data: {json}`` or ``data: [DONE]``.

    ``on_delta`` receives each text chunk instead of it being printed — the web
    frontend streams it to the browser; the CLI leaves it None and watches stdout.
    """
    line = line.strip()
    if not line.startswith(b"data:"):
        return
    payload = line[5:].strip()
    if payload == b"[DONE]":
        return
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return
    for ch in obj.get("choices", []):
        delta = ch.get("delta") or {}
        text = delta.get("content")
        if text:
            pieces.append(text)
            if on_delta is not None:
                on_delta(text)
            else:
                sys.stdout.write(text)
                sys.stdout.flush()


def _slim(metrics):
    """Shrink the bulky, low-signal parts of a metrics dict for the prompt.

    The analytic blocks (autopsy, aim_mode, breakdown, patterns, quarters,
    sliders, tapping, trust) are what the model reasons over and are kept whole.
    Only the fields that are long but redundant are capped: the 100+ stream
    segments (keep the 8 worst by std), the per-3s stamina bins (the summary
    keys stay) and the n<10 composition rows. Without this the raw JSON is
    ~100k chars and the tail (streams, tapping, breakdown) is truncated away.
    """
    import copy
    d = copy.deepcopy(metrics)
    st = d.get("streams")
    if isinstance(st, dict) and isinstance(st.get("segments"), list) \
            and len(st["segments"]) > 8:
        all_segs = st["segments"]
        st["segments"] = sorted(all_segs, key=lambda s: -(s.get("std_err") or 0))[:8]
        st["segments_shown"] = f"8 of {len(all_segs)} (worst by std)"
    prof = d.get("profile")
    if isinstance(prof, dict):
        stam = prof.get("stamina")
        if isinstance(stam, dict):
            stam.pop("bins", None)
        comp = prof.get("composition")
        if isinstance(comp, list):
            prof["composition"] = [c for c in comp if c.get("reported")]
    return d


def _compact(d, limit=48000):
    s = json.dumps(_slim(d), indent=1, default=float)
    return s if len(s) <= limit else s[:limit] + "\n... [truncated]"


def enrich_rows(rows, outdir):
    """Join the optional corpus caches onto each metrics dict, in place.

    When ``osu-critique stars`` / ``pp`` / ``status`` have run in ``outdir``,
    every coached run gets its star rating (``sr``), pp (``pp``) and online
    rank status (``rank_status``) without the caller asking. Missing caches are
    simply skipped — the core critique never depends on them.
    """
    from .metrics.difficulty import _load_json, effective_sr_mods
    if not outdir:
        return rows
    stars = _load_json(os.path.join(str(outdir), "stars_by_md5.json"))
    pp = _load_json(os.path.join(str(outdir), "pp_by_replay.json"))
    cache = _load_json(os.path.join(str(outdir), "beatmap_status.json"))
    index = _load_json(os.path.join(str(outdir), "lazer_md5_index.json"))
    ids = {}
    if cache and index:
        from .io import status as _status
        needed = {m.get("beatmap_md5") for _, m in rows if m.get("beatmap_md5")}
        ids = _status.beatmap_ids(index, needed)
    for _, m in rows:
        md5 = m.get("beatmap_md5")
        st = stars.get(md5) if md5 else None
        if st:
            base = st.get("NM")
            eff = st.get(effective_sr_mods(m.get("mod_string")) or "NM", base)
            m["sr"] = {"base": base, "effective": eff}
        rk = m.get("replay_md5")
        if rk and rk in pp:
            m["pp"] = pp[rk]
        bid = ids.get(md5) if md5 else None
        if bid is not None:
            rec = cache.get(str(bid)) or cache.get(bid)
            if rec:
                m["rank_status"] = rec.get("status")
    return rows


def build_user_message(metrics, baseline=None, profile=None, notes=None):
    parts = [f"## Metrics\n```json\n{_compact(metrics)}\n```"]
    if notes:
        from .annotations import prompt_block
        block = prompt_block(notes)
        if block:
            parts.append(block)
    if baseline:
        parts.append(f"## Baseline (previous play)\n```json\n{_compact(baseline)}\n```")
    if profile:
        parts.append(f"## Player profile\n{json.dumps(profile, indent=1)}")
    return "\n\n".join(parts)


def _run_row(name, m):
    """Compact per-run summary for the multi-run coach."""
    h = m["hit_error_ms"]
    p = m.get("patterns", {}) or {}
    q = m.get("quarters", []) or []

    def pat(k):
        d = p.get(k) or {}
        return round(100 * d.get("miss_rate", 0.0), 1)

    flag = "MISMATCH" if m.get("map_version_mismatch") else (
        "FAILED" if m.get("failed_play") else "")
    am = (m.get("aim_mode") or {}).get("distance_at_note_r") or {}
    classes = ((m.get("autopsy") or {}).get("shapes") or {}).get("classes") or []
    rev = next((c for c in classes if c["class"] == "near-reversal chain"), None)
    bd = m.get("breakdown") or {}
    casc = bd.get("cascades") or []
    ramp = bd.get("ramp") or {}
    sr = m.get("sr") or {}
    pp = m.get("pp") or {}
    return {
        "map": name,
        "acc_pct": round(100 * m["accuracy"], 1),
        "ur": round(m["ur"], 1),
        "mean_ms": round(h.get("mean", 0.0), 1),
        "aim_r": round(m["aim_px"].get("mean_norm", 0.0), 2),
        "arrive_r": (round(am["mean"], 2) if am.get("mean") is not None else "-"),
        "reversal_pct": (round(100 * rev["non300_rate"], 1)
                         if rev and rev["non300_rate"] is not None else "-"),
        "miss": m["counts_recorded"]["miss"],
        "whiffs": m["whiffed_presses"],
        "dense_miss_pct": pat("dense"),
        "stream_miss_pct": pat("stream"),
        "jump_miss_pct": pat("jump"),
        "bigjump_miss_pct": pat("bigjump"),
        "quarter_miss": [q_.get("miss", 0) for q_ in q],
        "cliff_px_ms": (round(bd["cliff"], 2) if bd.get("cliff") is not None else "-"),
        "cascade": (casc[0]["n"] if casc else "-"),
        "ramp_miss": ramp.get("miss", "-"),
        "eff_sr": (round(sr["effective"], 2) if sr.get("effective") is not None else "-"),
        "pp": (round(pp["pp"], 1) if pp.get("pp") is not None else "-"),
        "status": m.get("rank_status", "-") or "-",
        "flag": flag,
    }


def build_multi_user_message(rows, profile=None, notes=None):
    """Build the prompt for a cross-run critique (a folder of metrics JSONs).

    ``rows`` is a list of (map_name, metrics_dict) pairs. Presents a compact
    per-run table instead of N full JSON blobs so any number of runs fits."""
    lines = ["## Runs — %d plays (compact per-run stats)" % len(rows)]
    lines.append("| map | acc | UR | mean_ms | aim_r | arrive_r | miss | whiffs | "
                 "dense% | stream% | jump% | bigjump% | reversal% | Q1-Q4 miss | "
                 "effSR | pp | status | cliff | cascade | flag |")
    lines.append("|" + "---|" * 21)
    for name, m in sorted(rows, key=lambda r: r[1]["accuracy"]):
        r = _run_row(name, m)
        q = ",".join(str(x) for x in r["quarter_miss"]) if r["quarter_miss"] else "-"
        lines.append(
            f"| {r['map'][:40]} | {r['acc_pct']} | {r['ur']} | {r['mean_ms']:+.1f} "
            f"| {r['aim_r']:.2f} | {r['arrive_r']} | {r['miss']} | {r['whiffs']} "
            f"| {r['dense_miss_pct']} "
            f"| {r['stream_miss_pct']} | {r['jump_miss_pct']} | {r['bigjump_miss_pct']} "
            f"| {r['reversal_pct']} | {q} | {r['eff_sr']} | {r['pp']} "
            f"| {r['status']} | {r['cliff_px_ms']} | {r['cascade']} | {r['flag']} |")
    lines.append("")
    lines.append("Analyze the player ACROSS these runs: per-skill verdicts, "
                 "recurring weaknesses (patterns, quarters, whiffs, timing bias), "
                 "aim-vs-timing split, trends if any, and a prioritized practice "
                 "plan. Compare runs against each other — flag the worst and best "
                 "and explain the gap. Use the numbers; don't invent others.")
    parts = ["\n".join(lines)]
    if notes:
        from .annotations import prompt_block
        block = prompt_block(notes)
        if block:
            parts.append(block)
    if profile:
        parts.append(f"## Player profile\n{json.dumps(profile, indent=1)}")
    return "\n\n".join(parts)


def prepare_critique(metrics, outdir, baseline=None, profile=None,
                     prompt_file=None):
    """``(system, user, notes)`` for one run's critique — no network, no keys."""
    from .annotations import for_metrics

    system = load_system_prompt(prompt_file)
    notes = for_metrics(metrics, outdir)
    user = build_user_message(metrics, baseline, profile, notes=notes)
    return system, user, notes


def generate_critique(system, user, model=None, on_delta=None, key=None):
    """Run one chat call; returns ``(text, model)``. Raises without a key."""
    from .config import llm_base_url, llm_key, llm_model

    key = key or llm_key()
    if not key:
        raise RuntimeError(
            "no LLM key configured. Run `osu-critique setup` or set OSU_LLM_KEY.")
    base, mdl = llm_base_url(), model or llm_model()
    text = _call_chat(system, user, key, base, mdl, on_delta=on_delta)
    return text, mdl


def coach(metrics_path, baseline_path=None, profile=None, model=None,
          prompt_file=None):
    """Run the LLM critique; returns the critique text.

    ``metrics_path`` may be a single metrics JSON *or a directory* containing
    ``*_metrics.json`` files (e.g. the output folder from ``batch``) — in the
    latter case the critique covers all runs together.

    ``model`` overrides the configured model (setup wizard / OSU_LLM_MODEL).
    ``prompt_file`` overrides the built-in critique-framework prompt."""
    from .config import llm_base_url, llm_key, llm_model
    baseline = None
    if baseline_path:
        with open(baseline_path) as f:
            baseline = json.load(f)
    system = load_system_prompt(prompt_file)
    base, mdl = llm_base_url(), model or llm_model()
    print(f"note: coach using {mdl} @ {base}", file=sys.stderr)

    if os.path.isdir(metrics_path):
        rows = _load_metrics_dir(metrics_path)
        if not rows:
            raise RuntimeError(
                f"no *_metrics.json files found in directory {metrics_path!r} — "
                "run `osu-critique batch` first")
        enrich_rows(rows, metrics_path)
        from .annotations import all_notes
        wanted = {m.get("beatmap_md5") for _n, m in rows if m.get("beatmap_md5")}
        notes = [n for n in all_notes(metrics_path) if n["beatmap_md5"] in wanted]
        user = build_multi_user_message(rows, profile, notes=notes)
    else:
        try:
            with open(metrics_path) as f:
                metrics = json.load(f)
        except FileNotFoundError:
            raise RuntimeError(
                f"no such metrics file: {metrics_path!r} — run `osu-critique analyze "
                "<replay.osr> <map.osu> <tag>` first (it writes out/<tag>_metrics.json)") from None
        except json.JSONDecodeError:
            raise RuntimeError(f"{metrics_path!r} is not valid metrics JSON — "
                               "run `osu-critique analyze` to generate it") from None
        run_outdir = os.path.dirname(os.path.abspath(metrics_path))
        enrich_rows([(os.path.basename(metrics_path), metrics)], run_outdir)
        from .annotations import for_metrics
        notes = for_metrics(metrics, run_outdir)
        user = build_user_message(metrics, baseline, profile, notes=notes)
    # the key is only needed for the API call: report a bad metrics path first,
    # so a missing file is never masked by "no LLM key configured"
    key = llm_key()
    if not key:
        raise RuntimeError(
            "no LLM key configured. Run `osu-critique setup` (interactive wizard) "
            "or set OSU_LLM_KEY. For a key-free deterministic critique, run "
            "`osu-critique report <metrics.json>` instead.")
    try:
        return _call_chat(system, user, key, base, mdl)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LLM API error {e.code}: {e.read()[:300]!r}") from e
    except TimeoutError as e:
        raise RuntimeError(str(e)) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach {base} "
                           f"(offline or wrong base URL?): {e.reason}") from e


def _load_metrics_dir(path):
    """Load all *_metrics.json files in a directory as (map_name, metrics)."""
    import glob
    rows = []
    for p in sorted(glob.glob(os.path.join(path, "*_metrics.json"))):
        try:
            with open(p) as f:
                m = json.load(f)
            rows.append((m.get("map", os.path.basename(p)), m))
        except (json.JSONDecodeError, OSError):
            continue
    return rows
