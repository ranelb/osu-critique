# osu-critique

Data-driven osu! replay analysis and coaching. Parses a replay (`.osr`) and its
beatmap (`.osu`) and produces **validated** per-object metrics — hit error
(timing), aim error (spatial), pattern classification, stream segments, tapping
style, UR — plus charts, a deterministic report, and an optional AI critique.

The analysis core is **fully local: no API keys, no network, no account.** All
optional extras (AI coach, osu! profile) are bring-your-own-key.

> **Status: 0.1.1.** The analysis core is validated against real replays —
> `counts_detected` matches the game's `counts_recorded` on the golden test set
> (see [Validation](#validation-and-trust)). 11 tests, CI on Python 3.11/3.12.

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

Per-play metrics include:

- **Timing**: mean hit error (early/late bias), std → UR, distribution percentiles
- **Aim**: cursor distance from object centre at press time (in circle radii),
  per screen region
- **Patterns**: miss rates by spacing bucket — dense (≤2r), stream (2–4r),
  jump (4–7r), bigjump (>7r)
- **Streams**: every stream segment, with per-segment timing (std/UR) and
  alternation ratio (same-finger double-taps under pressure)
- **Tapping**: alternation ratio, same-key adjacencies, key balance, whiffed
  presses (taps that hit nothing — the rushing signal)
- **Sections**: quarter-by-quarter miss/error breakdown (fatigue detection)
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
osu-critique --version   # → osu-critique 0.1.1
```

The repo ships empty `replays/` and `maps/` folders: drop `.osr` replays and
`.osu`/`.osz` maps there and `osu-critique pair` will pick them up (`.osz`
archives are unpacked automatically).

### Install from a release (no git needed)

Every release ships a wheel (`osu_critique-0.1.1-py3-none-any.whl`) that works
on any OS — Python is required, git is not:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install https://github.com/ranelb/osu-critique/releases/download/v0.1.1/osu_critique-0.1.1-py3-none-any.whl
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
LLM base URL [https://api.openai.com/v1]:
LLM model — enter a custom name if you know yours
  (e.g. gpt-4o-mini, claude-sonnet-4-5, deepseek-chat) [gpt-4o-mini]:

[osu! profile — powers `osu-critique profile` via API v2]
osu! API client id (https://osu.ppy.sh/oauth/clients): ********
osu! API client secret: ********

[Paths — where your replays/maps live (auto-detected if empty)]
osu!lazer data dir [/home/you/.var/app/sh.ppy.osu/data/osu]:
output dir [out]:
```
```

- Every value is optional — press Enter to accept defaults or skip.
- Secrets are masked while typing and stored at
  `~/.config/osu-critique/config.json` with mode `0600`.
- `osu-critique setup --show` prints the effective config with secrets masked.
- The coach works with **any model name you have access to** — set it in the
  wizard, via `OSU_LLM_MODEL`, or per-run with `coach --model <name>`.
- Anything in the wizard can be overridden per-run by the matching env var
  (precedence: **env var > config file > default**).

## Usage

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
    [--model <any-model-name>]

# osu! profile stats (API v2 if credentials set, else HTML fallback)
osu-critique profile <username>
# profile via the official API requires credentials (setup wizard or env vars);
# the unofficial HTML fallback only runs with the explicit --scrape opt-in:
osu-critique profile <username> --scrape
```

Output: `out/<tag>_metrics.json`, plus `out/<tag>_charts.png` with `--charts`
(four panels: hit-error histogram, error-over-time, spatial result map, aim
error histogram).

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
| `OSU_LLM_BASE_URL` | `https://api.openai.com/v1` | LLM endpoint (works with OpenRouter, local servers, …) |
| `OSU_LLM_MODEL` | `gpt-4o-mini` | default coach model (override per run with `--model`) |
| `OSU_CLIENT_ID` / `OSU_CLIENT_SECRET` | — | osu! API v2 credentials for `profile` (optional) |
| `OSU_ALLOW_SCRAPE` | `false` | allow the unofficial HTML `profile` fallback when no API credentials are set (also config `allow_scrape`) |
| `OSU_CONFIG_DIR` | `~/.config/osu-critique` | where the config file lives |

## How it works

1. **Parse** the `.osr`/`.osu` with the `slider` library.
2. **Frames** — replay actions sorted by time (some export tools emit
   out-of-order trailing frames; sorting is required for correct press
   detection and cursor interpolation).
3. **Assignment** — each object gets its nearest unused keypress, but only if
   the cursor is within the circle's radius at press time (mirrors osu!'s own
   aim requirement). Judgements use the map's OD windows.
4. **Calibration** — the time scale is auto-selected (mod-based first, then
   unscaled) to best match the replay's recorded miss count. Some lazer
   exports and mod flags are misleading; this step disambiguates.
5. **Metrics** — hit/aim error, UR, pattern buckets, regions, quarters, stream
   segments, whiffs, tapping style, plus `failed_play` / `map_version_mismatch`
   flags.
6. **Tiers** — `report` renders a deterministic critique from the JSON;
   `coach` upgrades it with one LLM API call (system prompt encodes the same
   critique framework; optional baseline + profile give it context).

## Validation and trust

The pipeline is validated against a golden set: on every fixture, `counts_detected`
matches the game's `counts_recorded` (exact on the perfect-FC and synthetic
fixtures; within a few objects on real messy plays, where slider-tick judgement
is the known gap). When the two disagree by more than a small delta, the play is
either a **failed play** or a **map-version mismatch** — both are flagged in the
JSON rather than silently trusted.

## Edge cases and limitations

- **Relax replays**: the game auto-hits from cursor position, so aim data is
  meaningless and timing reflects cursor arrival, not taps.
- **Slider ticks**: judgement counts include slider ticks that head-based
  assignment cannot see; slider-heavy maps' accuracy is slightly optimistic.
- **Lazer export time convention**: some exports store frames in map-time, not
  real-time; calibration handles it automatically.
- **`map_version_mismatch`**: replay ends well before the map's last object —
  analysis is only reliable up to the replay end.
- **Mod flags**: a replay may claim DT/HT while its frames are at map-time
  (lazer export quirk); the scale calibration picks the consistent interpretation.

## Development

```sh
pip install -e ".[dev]"
pytest -q                     # 11 tests, no network needed
```

- `tests/fixtures/` — committed golden replays + maps, plus synthetic
  edge-case fixtures (see `tests/fixtures/ATTRIBUTION.md`).
- `scripts/make_synthetic_fixtures.py` — regenerates the synthetic fixtures and
  can anonymize `.osr` player names (`--anonymize`).
- CI (`.github/workflows/test.yml`) runs the suite on Python 3.11 and 3.12.

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
