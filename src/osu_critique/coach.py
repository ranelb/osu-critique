"""AI critique (bring-your-own-key): one LLM API call from a metrics JSON.

No agent loop, no harness: everything is precomputed into the metrics JSON,
so the critique is a single chat-completions request. OpenAI-compatible
endpoints only (works with OpenAI, OpenRouter, local servers, etc.).

Environment:
    OSU_LLM_KEY        API key (required)
    OSU_LLM_BASE_URL   default https://api.openai.com/v1
    OSU_LLM_MODEL      default gpt-4o-mini
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """You are an osu! gameplay analyst. The user gives you a metrics JSON
produced by a replay analysis pipeline (per-object hit/aim error derived from an
.osr + .osu pair), optionally a baseline JSON from earlier plays, and optionally
their osu! profile stats.

Critique framework — use the numbers, don't invent others:
- Timing: mean hit error sign (early/late) and consistency (std -> UR, UR = std*10).
  |bias| > 6ms with consistent sign on most plays -> suggest testing a universal offset.
- Aim: mean aim error in circle radii (0.30-0.45 good; aim error staying flat as
  cursor-velocity/difficulty rises is a sign of a strong aim ceiling).
- Whiffed presses: presses that hit nothing; rate = whiffs / used presses; >10%
  indicates rushing / tapping before the cursor lands on the target.
- Patterns: miss rates by spacing bucket (dense <=2r, stream 2-4r, jump 4-7r,
  bigjump >7r). A pattern with a miss rate far above the others is the primary target.
- Streams: per-segment std (ms) and alternation ratio. Segment std > 30ms or
  alternation < 90% = rhythm collapse under sustained tapping. Long segments failing
  while short ones hold = sustain/rhythm issue.
- Quarters: misses clustering in one quarter = section-specific difficulty;
  timing std degrading toward Q4 = fatigue.
- Tapping: alternation ratio > 90% is good; high same-key adjacency = double-taps
  under pressure; key balance A vs B.
- Flags in the JSON: failed_play = the run ended early (only critique the played
  portion, and say so); map_version_mismatch = replay/map timing mismatch, analysis
  unreliable past the replay end; relax mod = the game auto-hit from cursor position,
  so aim data is meaningless and timing reflects cursor arrival, not taps.

Output: a concise markdown critique with (1) a verdict summary, (2) strengths,
(3) weaknesses ranked by impact, (4) 3-5 specific practice recommendations tied to
the actual numbers, (5) what the data cannot show. Be honest and direct; no fluff,
no generic advice. If a baseline is provided, explicitly flag improvement or
regression vs baseline. If the player profile is provided, use it for context
(hours, rank, playstyle) but do not let it override the play data."""


def _call_chat(system: str, user: str, key: str, base_url: str, model: str) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.4,
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"]


def _compact(d, limit=12000):
    s = json.dumps(d, indent=1, default=float)
    return s if len(s) <= limit else s[:limit] + "\n... [truncated]"


def build_user_message(metrics, baseline=None, profile=None):
    parts = [f"## Metrics\n```json\n{_compact(metrics)}\n```"]
    if baseline:
        parts.append(f"## Baseline (previous play)\n```json\n{_compact(baseline)}\n```")
    if profile:
        parts.append(f"## Player profile\n{json.dumps(profile, indent=1)}")
    return "\n\n".join(parts)


def coach(metrics_path, baseline_path=None, profile=None):
    """Run the LLM critique; returns the critique text."""
    from .config import llm_base_url, llm_key, llm_model
    key = llm_key()
    if not key:
        raise RuntimeError(
            "no LLM key configured. Run `osu-critique setup` (interactive wizard) "
            "or set OSU_LLM_KEY. For a key-free deterministic critique, run "
            "`osu-critique report <metrics.json>` instead.")
    with open(metrics_path) as f:
        metrics = json.load(f)
    baseline = None
    if baseline_path:
        with open(baseline_path) as f:
            baseline = json.load(f)
    user = build_user_message(metrics, baseline, profile)
    try:
        return _call_chat(SYSTEM_PROMPT, user, key, llm_base_url(), llm_model())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LLM API error {e.code}: {e.read()[:300]!r}") from e
