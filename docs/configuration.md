# Configuration

Settings resolve as **environment variable > config file > auto-detection >
default**. Everything below can be set in the wizard (`osu-critique setup`)
instead of as env vars. `osu-critique paths` prints everything the tool
resolved (with existence markers).

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

## Paths and platform support

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

## Environment variables

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
