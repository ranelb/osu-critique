# osu-critique

Data-driven osu! replay analysis and coaching. Parses a replay (`.osr`) and its
beatmap (`.osu`) and produces **validated** per-object metrics — hit error
(timing), aim error (spatial), pattern classification, stream segments, tapping
style, UR — plus charts, a deterministic report, and an optional AI critique.

The analysis core is **fully local: no API keys, no network, no account.** All
optional extras (AI coach, osu! profile) are bring-your-own-key.

> **Status: 0.5.0.** Presses are resolved the way the game resolves them (in
> press order), hit windows and geometry follow the mods, and every run states
> how far its own judgement can be trusted. Counts match the game exactly on the
> golden fixtures and land within a few objects on the real replays used as a
> gate — see [Validation](#validation-and-trust). 90 tests, CI on Python
> 3.11/3.12. Every run also profiles the map (effective BPM, families, stamina,
> chains — docs/profile.md), re-derives the cursor's arrival from the frames
> (docs/aim.md) and autopsies the misses themselves (docs/autopsy.md), so a Relax
> replay is analysable too.

## Table of Contents

- [Features](#features)
  - [Getting a critique — three ways](#getting-a-critique--three-ways)
  - [Supported LLM](#supported-llm)
- [Install](#install)
  - [Install from a release (no git needed)](#install-from-a-release-no-git-needed)
- [First-time setup (optional, ~30 seconds)](#first-time-setup-optional-30-seconds)
- [Commands](#commands)
  - [Quick example](#quick-example)
- [Configuration](#configuration)
  - [Paths and platform support](#paths-and-platform-support)
- [How it works](#how-it-works)
- [Validation and trust](#validation-and-trust)
- [Edge cases and limitations](#edge-cases-and-limitations)
- [Development](#development)
- [Privacy, attribution, and terms](#privacy-attribution-and-terms)
- [License](#license)

## Features

| Tier | Command | Needs keys? | What you get |
|---|---|---|---|
| **Core** | `analyze`, `pair`, `batch` | no | per-object metrics JSON + charts |
| **Report** | `report` | no | deterministic, rule-based critique |
| **Coach** | `coach` | LLM key (BYO) | full natural-language critique |
| **Profile** | `profile` | osu! API creds (BYO, optional) | player stats for context |

Replays and maps are found automatically from **osu!lazer** (Windows, Linux
Flatpak/AppImage, macOS), **osu!stable** (Windows), or the project's own
`replays/` + `maps/` folders — no path configuration required. Every source is
paired by **exact beatmap MD5** (the same rule osu! itself uses).

### Getting a critique — three ways

The same metrics JSON can be turned into a critique at three levels:

| Way | Command | Needs? | What you get |
|---|---|---|---|
| **Deterministic** | `report <metrics.json\|dir>` | nothing | rule-based critique from thresholds — no AI, no keys, fully offline (a directory prints the cross-run aggregate) |
| **One-command AI** | `coach <metrics.json\|dir> [--all]` | LLM API key | full natural-language critique via a single API call — **streamed live** (tokens appear as generated); point at a folder of runs for a cross-run critique, or use `--all` for the whole output dir |
| **Bring-your-own AI** | `prompt <metrics.json>` | nothing | the framework prompt + your data, ready to paste into any AI you choose (then `coach --prompt` to reuse a custom framework) |

`coach` and `prompt` accept the same optional `--baseline` (an earlier metrics
JSON, for improvement/regression detection) and `--profile <username>` (osu!
player stats for context).

### Supported LLM

The AI coach has been tested with **one model only: DeepSeek V4 Flash**
(`deepseek-v4-flash`, base URL `https://api.deepseek.com`). It is the default
and the recommended/supported configuration. Other OpenAI-compatible models
and endpoints may work (the client is generic), but they are untested —
expect the critique quality to vary with the model.

Per-play metrics include:

- **Timing**: mean hit error (early/late bias), std → UR, distribution percentiles
- **Aim**: cursor distance from object centre at press time (in circle radii),
  per screen region
- **Aim (cursor arrival)**: the cursor path itself — distance at the note
  instant, closest approach within ±320 ms and when it peaks, the share reached
  but not on time, the along/lateral split, and the ceiling curve (distance at
  the note against the cursor speed the jump demands). Works with or without
  Relax ([docs/aim.md](docs/aim.md))
- **Miss autopsy**: the shape classes (5-note windows: near-reversal chain /
  cornered box / flow / mixed) with n-gated off-300 rates, the press-time arrival
  margin, press vs arrival timing, per-leg heading error and path efficiency,
  mid-travel "stutter" presses, and each miss with its own press and geometry
  ([docs/autopsy.md](docs/autopsy.md))
- **Patterns**: miss rates by spacing bucket — dense (≤2r), stream (2–4r),
  jump (4–7r), bigjump (>7r)
- **Streams**: every stream segment, with per-segment timing (std/UR) and
  alternation ratio (same-finger double-taps under pressure)
- **Tapping**: alternation ratio, same-key adjacencies, key balance, whiffed
  presses (taps that hit nothing — the rushing signal)
- **Sections**: quarter-by-quarter miss/error breakdown (fatigue detection)
- **Whiffs by cause**: every unused press explained — mash, off-target (the
  cursor was not on the circle), beside a slider head, duplicate, or after the map
- **Aim ceiling**: aim error (circle radii) fitted against cursor speed, with the
  slowest-to-fastest quartile means — a static "0.30-0.45r is good" hides the slope
- **Map profile**: the map's own character — effective BPM and real note gaps,
  pattern families (`kind_divisor_spacing`) with n-gated hit rates, slider
  character (path length and the cursor speed demanded), stamina (notes/s,
  longest sustained run, breaks), chains with hit rate by position, and
  signed bias per family ([docs/profile.md](docs/profile.md))
- **Trust**: per-count deltas against the game's own recorded hits, the scale the
  calibration chose, and whether the judgement can be trusted at all
- **Flags**: `failed_play`, `map_version_mismatch`, mods

## Install

Requires Python ≥ 3.10.

```sh
git clone <repo-url> && cd osu-critique
python3 -m venv .venv && source .venv/bin/activate

pip install -e .            # analysis core (numpy + slider)
pip install -e ".[charts]"  # + matplotlib, for --charts PNG output
```

This installs the `osu-critique` command. Verify:

```sh
osu-critique --version   # → osu-critique 0.5.0
```

The repo ships empty `replays/` and `maps/` folders: drop `.osr` replays and
`.osu`/`.osz` maps there and `osu-critique pair` will pick them up (`.osz`
archives are unpacked automatically).

### Install from a release (no git needed)

Every release ships a wheel (`osu_critique-0.5.0-py3-none-any.whl`) that works
on any OS — Python is required, git is not:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install https://github.com/ranelb/osu-critique/releases/download/v0.5.0/osu_critique-0.5.0-py3-none-any.whl
pip install matplotlib   # optional, for --charts
```

## First-time setup (optional, ~30 seconds)

```sh
osu-critique setup
```

An interactive wizard collects your optional keys and replay/map paths:

```
[LLM coach — powers `osu-critique coach`]
LLM API key (OpenAI-compatible): ********
LLM base URL [https://api.deepseek.com]:
LLM model — enter a custom name if you know yours
  (recommended: deepseek-v4-flash) [deepseek-v4-flash]:

[osu! profile — powers `osu-critique profile` via API v2]
osu! API client id (https://osu.ppy.sh/oauth/clients): ********
osu! API client secret: ********

[Paths — where your replays/maps live (auto-detected if empty)]
osu!lazer data dir [/home/you/.var/app/sh.ppy.osu/data/osu]:
output dir [out]:
```

- Every value is optional — press Enter to accept defaults or skip.
- Secrets are masked while typing and stored at
  `~/.config/osu-critique/config.json` with mode `0600`.
- `osu-critique setup --show` prints the effective config with secrets masked.
- The coach works with **any model name you have access to** — set it in the
  wizard, via `OSU_LLM_MODEL`, or per-run with `coach --model <name>`.
- Anything in the wizard can be overridden per-run by the matching env var
  (precedence: **env var > config file > default**).

## Commands

```sh
# analyze a single replay against its map
osu-critique analyze <replay.osr> <map.osu> [tag] [--charts]
# resolve replay->map pairs without analyzing (auto-detects all sources)
osu-critique pair

# pair + analyze every available replay + aggregate table
osu-critique batch --charts

# show every resolved path (auto-detection diagnostics)
osu-critique paths

# deterministic critique from a metrics JSON (no LLM, no keys)
osu-critique report out/<tag>_metrics.json [--baseline out/<other>_metrics.json]

# AI critique — one LLM API call, no harness/agent required
osu-critique coach out/<tag>_metrics.json \
    [--baseline out/<other>_metrics.json] \
    [--profile <username>] \
    [--model <any-model-name>] \
    [--prompt <custom-prompt-file>]

# bring your own AI: print the critique-framework prompt, or a full
# ready-to-paste prompt (framework + your metrics) for any LLM of your choice
osu-critique prompt
osu-critique prompt out/<tag>_metrics.json [--baseline ...] [--profile <username>]

# osu! profile stats (API v2 if credentials set, else HTML fallback)
osu-critique profile <username>
# profile via the official API requires credentials (setup wizard or env vars);
# the unofficial HTML fallback only runs with the explicit --scrape opt-in:
osu-critique profile <username> --scrape
```

Output: `out/<tag>_metrics.json`, `out/<tag>_objects.json` (one record per hit
object — rhythm snap, spacing, flow angle, strains; the schema is in
[docs/object_schema.md](docs/object_schema.md), skip it with `--no-objects`),
plus, with `--charts`, `out/<tag>_charts.png` (four panels: hit-error histogram,
error-over-time, spatial result map, aim error histogram), `out/<tag>_aim.png`
(six cursor-arrival panels — [docs/aim.md](docs/aim.md)) and
`out/<tag>_windows.png` (the worst arrival stretches — [docs/autopsy.md](docs/autopsy.md)).
The cursor-arrival and miss-autopsy blocks are computed for every run; skip them
with `--no-aim` / `--no-autopsy`.

### Quick example

```sh
osu-critique analyze tests/fixtures/aaaaa.osr tests/fixtures/aaaaa.osu myrun --charts
osu-critique report out/myrun_metrics.json
osu-critique coach out/myrun_metrics.json --profile yourusername
```

## Configuration

Settings resolve as **environment variable > config file > auto-detection >
default**. All of the following can be set in the wizard (`osu-critique setup`)
instead of as env vars. `osu-critique paths` prints everything the tool
resolved (with existence markers).

### Paths and platform support

Paths are never hardcoded to a single location: known installs are probed and
the first one that exists wins, per platform:

| Install | Locations probed (first existing wins) |
|---|---|
| osu!lazer, Windows | `%APPDATA%/osu` |
| osu!lazer, Linux Flatpak | `~/.var/app/sh.ppy.osu/data/osu` |
| osu!lazer, Linux AppImage / macOS | `~/.local/share/osu` (macOS: `~/Library/Application Support/osu`) |
| osu!stable (Windows only) | `%LOCALAPPDATA%/osu!` |
| Project folders | `./replays` + `./maps` (any OS — drop `.osr`/`.osu`/`.osz` there) |

If you need a non-standard location, set the matching env var (or `setup`):
it always wins over detection.

| Variable | Default | Purpose |
|---|---|---|
| `OSU_LAZER_DATA` | auto-detected | osu!lazer data root |
| `OSU_LAZER_EXPORTS` | `<lazer data>/exports` | lazer replay exports |
| `OSU_LAZER_FILES` | `<lazer data>/files` | lazer content-addressed map store |
| `OSU_ONLINE_DB` | `<lazer data>/online.db` | lazer beatmap SQLite db |
| `OSU_STABLE_ROOT` | auto-detected (Windows) | osu!stable install root |
| `OSU_REPLAYS_DIR` / `OSU_MAPS_DIR` | `replays` / `maps` | project folders |
| `OSU_CACHE_DIR` | `~/.cache/osu-critique` | extracted `.osz` contents |
| `OSU_OUTDIR` | `out` | metrics/charts output dir |
| `OSU_LLM_KEY` | — | LLM API key for `coach` (OpenAI-compatible) |
| `OSU_LLM_BASE_URL` | `https://api.deepseek.com` | LLM endpoint (OpenAI-compatible; works with OpenRouter, local servers, …) |
| `OSU_LLM_MODEL` | `deepseek-v4-flash` | default coach model — the tested/recommended model (override per run with `--model`) |
| `OSU_LLM_TIMEOUT` | `300` | total wall-clock deadline (seconds) for an LLM critique call — raise it for very large multi-run folders, lower it to fail fast |
| `OSU_MEMORY_LIMIT_GB` | `6` | hard address-space cap per process (Linux) so a runaway allocation fails fast with MemoryError instead of thrashing the machine into swap — set `0` to disable |
| `OSU_CLIENT_ID` / `OSU_CLIENT_SECRET` | — | osu! API v2 credentials for `profile` (optional) |
| `OSU_ALLOW_SCRAPE` | `false` | allow the unofficial HTML `profile` fallback when no API credentials are set (also config `allow_scrape`) |
| `OSU_CONFIG_DIR` | `~/.config/osu-critique` | where the config file lives |

## How it works

1. **Parse** the `.osr`/`.osu` with the `slider` library.
2. **Frames** — replay actions sorted by time (some export tools emit
   out-of-order trailing frames; sorting is required for correct press
   detection and cursor interpolation).
3. **Judgement** — objects are walked in time order and each takes the first
   press inside its window whose cursor is on the circle, exactly as the game
   does: presses are consumed in order and never reused. The hit windows and the
   circle radius behind that gate come from the **mod-adjusted** difficulty
   (Hard Rock raises OD/AR/CS and reflects the playfield vertically, Easy halves
   them).
4. **Calibration** — the time scale is auto-selected (mod-based first, then
   unscaled) by the whole recorded count vector, not by the miss count alone.
   Some lazer exports and mod flags are misleading; this step disambiguates.
5. **Metrics** — hit/aim error, UR (also as a share of the 300-window), aim error
   against cursor speed, pattern buckets, regions, quarters, stream segments,
   whiffs by cause, tapping style, plus `failed_play` / `map_version_mismatch`
   flags and a `trust` block.
6. **Cursor arrival** — the frames are sampled around every note to measure where
   the cursor actually was: distance at the note, closest approach and its
   timing, the along/lateral split and the speed-conditioned ceiling curve
   (`metrics.aim_mode`). This needs no taps, so it is the whole aim picture on a
   Relax replay ([docs/aim.md](docs/aim.md)).
7. **Miss autopsy** — the shape classes, the press-time arrival margin, press
   vs arrival timing, per-leg heading and path efficiency, mid-travel presses and
   each miss with its own press and geometry (`metrics.autopsy`,
   [docs/autopsy.md](docs/autopsy.md)). Under Relax the tap-derived sections are
   reported as unavailable rather than as zero.
8. **Records** — every object is written out with its rhythm snap, spacing, flow
   angle and strains (`out/<tag>_objects.json`): the schema later analyses read.
9. **Tiers** — `report` renders a deterministic critique from the JSON;
   `coach` upgrades it with one LLM API call (system prompt encodes the same
   critique framework; optional baseline + profile give it context).

## Validation and trust

On every committed fixture, `counts_detected` matches the game's
`counts_recorded` exactly (perfect-FC and synthetic fixtures included). On four
real replays used as a gate the judged counts land within a few objects, with
miss counts of 66 vs 62, 66 vs 55, 20 vs 21 and 5 vs 5 — the press-order judge
replaced a nearest-press rule that reported 117 misses on the first of those.

Every run also states its own trust: `trust.count_deltas` is the per-count
difference, `trust.within_tolerance` applies the thresholds (miss within
max(3, 2% of judged objects); the whole vector within max(5, 5%)), and
`trust.notes` records why a play is not trustworthy (a failed play, a
`map_version_mismatch`, relax). The console summary and the deterministic report
surface it before anything else is concluded.

## Edge cases and limitations

- **Relax replays**: the game auto-hits from cursor position, so press-time aim,
  whiffs and tapping are the game's, not the player's — read `aim_mode` (cursor
  arrival) instead. Timing there is cursor arrival, not taps.
- **Sliders are judged by their head**: the game also judges slider ticks and
  the follow path (the .osr counts themselves exclude ticks — the four counts sum
  to the map's object count). Presses consumed by a slider body rather than its
  head appear as `whiffs.slider_head`; treat slider-heavy miss counts as
  approximate.
- **Mods**: Hard Rock (OD/AR ×1.4, CS ×1.3, playfield reflected vertically) and
  Easy are applied to windows and geometry; DT/HT go through the time scale.
  HD/FL/NF change nothing measurable here. Relax/AutoPilot plays are flagged and
  judged from the cursor-arrival block.
- **Lazer export time convention**: some exports store frames in map-time, not
  real-time; calibration handles it automatically.
- **`map_version_mismatch`**: replay ends well before the map's last object —
  analysis is only reliable up to the replay end.
- **Mod flags**: a replay may claim DT/HT while its frames are at map-time
  (lazer export quirk); the scale calibration picks the consistent interpretation.

## Development

```sh
pip install -e ".[dev]"
pytest -q                     # 90 tests, no network needed
```

- `tests/fixtures/` — committed golden replays + maps, plus synthetic
  edge-case fixtures (see `tests/fixtures/ATTRIBUTION.md`).
- `src/osu_critique/metrics/aim.py` — the cursor-arrival ("aim mode") block and
  its six-panel figure (`docs/aim.md`).
- `src/osu_critique/metrics/autopsy.py` — the miss-autopsy block: shape classes,
  arrival margin, press-vs-arrival, legs, stutter and the misses themselves
  (`docs/autopsy.md`).
- `scripts/autopsy.py` — a thin printer over both blocks for one replay (plus the
  worst-arrival table). It used to be the reference implementation; the numbers
  now come from the library, so they cannot drift.
- `scripts/make_synthetic_fixtures.py` — regenerates the synthetic fixtures
  (including the Relax `synth_rx` pair) and can anonymize `.osr` player names
  (`--anonymize`).
- CI (`.github/workflows/test.yml`) runs the suite on Python 3.11 and 3.12.

## Roadmap

What is planned and why (miss autopsy, slider bodies, cross-attempt structure)
lives in [docs/ROADMAP.md](docs/ROADMAP.md) — read it before changing the
analysis; it also records the traps that have already bitten (the snap/divisor
convention, the calibration override, population gates).

## Privacy, attribution, and terms

- Developed with heavy use of AI coding assistance.
- Real replay fixtures are the author's own plays, **anonymized**
  (`TestPlayer`); beatmap extracts are credited to their mappers in
  `tests/fixtures/ATTRIBUTION.md`.
- The `profile` HTML-scrape fallback is **unofficial and opt-in only**
  (`--scrape` flag or `allow_scrape` config option); the default path is the
  official API v2, and the osu! Terms of Service should be respected.

## License

MIT. Third-party libraries: `slider` (MIT), `numpy`, `matplotlib`.
Not affiliated with osu! / ppy Pty Ltd; osu! is a registered trademark of
Dean Herbert.
