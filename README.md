# osu-critique

Data-driven osu! replay analysis. Parses a replay (`.osr`) and its beatmap
(`.osu`) and produces validated per-object metrics: hit error (timing), aim
error (spatial), pattern classification, stream segments, tapping style, UR —
plus charts and a deterministic report. No API keys needed for analysis.

> **Status: 0.1.0 (early).** The analysis core is validated against real replays
> (`detected` counts match the game's recorded counts). `coach` (AI critique) and
> `profile` (osu! integration) are implemented as bring-your-own-key extras.

## Install

```sh
pip install -e .          # analysis core (numpy + slider)
pip install -e ".[charts]"   # + matplotlib for PNG charts
```

## Usage

```sh
# analyze a single replay against its map
osu-critique analyze <replay.osr> <map.osu> [tag] [--charts]

# resolve replay->map pairs (danser folder library, or lazer exports by MD5)
osu-critique pair --source danser
osu-critique pair --source lazer

# pair + analyze everything + aggregate table
osu-critique batch --source all --charts

# deterministic critique from a metrics JSON (no LLM, no keys)
osu-critique report out/<tag>_metrics.json

# AI critique (bring your own LLM key — single API call, no harness)
export OSU_LLM_KEY=sk-...
osu-critique coach out/<tag>_metrics.json [--baseline out/<other>_metrics.json] [--profile ran27]

# osu! profile stats (bring your own API v2 credentials, or HTML fallback)
export OSU_CLIENT_ID=... OSU_CLIENT_SECRET=...
osu-critique profile <username>
```

Output: `out/<tag>_metrics.json` (+ `out/<tag>_charts.png` with `--charts`).

## Configuration (environment variables)

| Variable | Default |
|---|---|
| `OSU_DANSER_REPLAYS` | `~/Documents/Danser/Replays` |
| `OSU_DANSER_SONGS` | `~/Documents/Danser/Songs` |
| `OSU_LAZER_DATA` | `~/.var/app/sh.ppy.osu/data/osu` |
| `OSU_LAZER_EXPORTS` | `<lazer data>/exports` |
| `OSU_LAZER_FILES` | `<lazer data>/files` |
| `OSU_ONLINE_DB` | `<lazer data>/online.db` |
| `OSU_OUTDIR` | `out` |
| `OSU_LLM_KEY` | API key for `coach` (OpenAI-compatible endpoint) |
| `OSU_LLM_BASE_URL` | default `https://api.openai.com/v1` |
| `OSU_LLM_MODEL` | default `gpt-4o-mini` |
| `OSU_CLIENT_ID` / `OSU_CLIENT_SECRET` | osu! API v2 credentials for `profile` (optional; HTML fallback works without them) |

## How it works (briefly)

1. **Parse** via the `slider` library (`.osr`/`.osu` formats).
2. **Frames**: replay actions sorted by time (some export tools emit
   out-of-order trailing frames).
3. **Assignment**: each object gets its nearest unused keypress, but only if
   the cursor is within the circle's radius at press time (mirrors osu!'s own
   aim requirement). Classification uses the map's OD windows.
4. **Calibration**: the time scale is auto-selected (mod-based first, then
   unscaled) to best match the replay's recorded miss count — some lazer
   exports carry misleading mod flags.
5. **Metrics**: hit/aim error, UR, pattern buckets (dense/stream/jump/bigjump),
   screen regions, time quarters, stream segments (per-segment UR + alternation),
   whiffs, tapping style. Plus `failed_play` / `map_version_mismatch` flags.

Validation: when `counts_detected` ≈ `counts_recorded`, the assignment is
trustworthy. Large gaps mean a failed play or a map-version mismatch (flagged
in the JSON).

## Limitations

- Relax replays: the game auto-hits from cursor position, so aim data is
  meaningless and timing reflects cursor arrival, not taps.
- Slider ticks: judgement counts include ticks the head-based assignment can't
  see; treat slider-heavy maps' accuracy as slightly optimistic.
- Lazer export time convention: some exports store frames in map-time (not
  real-time); the calibration step handles this automatically.

## Roadmap

- **Phase C (done)**: BYO-key extras — `coach` (LLM critique, single API call) and
  `profile` (osu! API v2 + HTML fallback), pinned `slider==0.8.4`, golden fixtures,
  GitHub Actions CI.
- **Phase D**: release polish — packaging, docs, example output.

## Privacy / terms

- `tests/fixtures/` contains the author's own replays (username visible). Remove
  the directory if you don't want them in your fork; tests then skip or use
  `OSU_TEST_*` env vars.
- The `profile` HTML-scrape fallback is unofficial; prefer the official API v2
  and respect the osu! Terms of Service.

## License

MIT. Third-party parsers used: `slider` (MIT), `numpy`, `matplotlib`.
Not affiliated with osu! / ppy Pty Ltd; osu! is a registered trademark of
Dean Herbert. Respect the osu! Terms of Service when using the API.
