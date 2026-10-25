# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```sh
pip install -e ".[dev]"          # install (add ".[charts]" for matplotlib)
pytest -q                        # full suite (~270; 45 need [web], 6 need the author's replays)
osu-critique index [--rebuild|--check]   # rebuild/refresh out/index.sqlite (derived)
osu-critique serve               # local web frontend on :8765 (needs .[web])
osu-critique annotate add --map <md5> [--run <replay_md5>] [--t 2:14.312] "note"
osu-critique export [--install|--run]   # opt-in; needs export.enabled
osu-critique digest                     # ingest new replays + write the digest
pytest tests/test_judge.py -q    # one file
pytest tests/test_judge.py::test_name -q   # one test
osu-critique batch --charts      # pair + analyze every replay in replays/ and the osu! install
osu-critique analyze <replay.osr> <map.osu> [tag] [--charts]
osu-critique report out/<tag>_metrics.json   # deterministic critique, no keys
```

CI (`.github/workflows/test.yml`) runs `pytest -q` on Python 3.10, 3.12, 3.14. Releases run from tags via `.github/workflows/release.yml`.

## Architecture

The analysis core is fully local and deterministic; the LLM pieces are optional layers on top of its JSON output.

- **Pipeline** (`src/osu_critique/report.py: analyze`): parse `.osr`/`.osu` (via the pinned `slider==0.8.4` library) → sort frames by time → judge presses against objects → calibrate the time base → compute metrics → write `out/<tag>_metrics.json` and `out/<tag>_objects.json`. `docs/internals.md` has the step-by-step version.
- **Judgement** (`metrics/assignment.py: judge`) is the core invariant: objects are walked in time order, each takes the first press inside its mod-adjusted hit window whose cursor is on the circle, and presses are consumed once. Window and circle radius come from the mod-adjusted difficulty (`io/beatmap.py`). Changes here must be re-checked with `scripts/judge_drift.py` against the game's recorded counts (needs the author's replays).
- **Calibration**: the time scale tries `[mod_scale, 1.0]` and keeps the lower weighted L1 over the whole count vector, not just misses. Some lazer exports store frames in map-time while the mod flag says otherwise; both clocks are reported in `metrics.time_base`.
- **Metrics** live in `src/osu_critique/metrics/`. Each block is a separate module that `report.py` assembles; `aim.py` (cursor arrival, relevant for Relax replays where taps are meaningless) and `autopsy.py` (miss shapes) are the largest. Tap-derived sections must report "unavailable" under Relax, not zero.
- **Tiers** are separate entry points over the same JSON: `report.py` (rule-based, offline), `coach.py` (one LLM call, DeepSeek V4 Flash by default, OpenAI-compatible), and `prompt` (framework + data for pasting into any AI). `profile.py` fetches osu! player stats (API v2, HTML scrape only with `--scrape` / `allow_scrape`).
- **Config and path discovery**: `config.py` resolves settings as env var (`OSU_*`) > config file > auto-detection > default. `io/pairing.py` finds replay↔map pairs across osu!lazer, osu!stable and the repo's `replays/` + `maps/`. `cli.py` is the `argparse` front end; `osu-critique paths` prints every resolved path.
- **Index** (`index.py`, `mapmeta.py`, `docs/index.md`): `out/index.sqlite` is a **projection** of `out/*_metrics.json` for the web frontend — listing/filter scalars plus a `beatmaps` row parsed from the `.osu`. `analyze`/`batch` upsert; `index --rebuild`/`--check` are the maintenance commands. Heavy blocks and per-object records stay in the JSON.
- **Export/digest** (`export.py`, `digest.py`, `docs/export.md`): opt-in only (`export.enabled`), never self-scheduled. Drives BeatmapExporter's text menu (`status …` / `reset`) through a pty; the pinned sha256 lives in `export_assets.json` and the release workflow attaches the binaries. `digest` ingests `.osr` newer than `out/digests/.last` and writes a deterministic markdown summary — no model in that path, ever.
- **Report** (`report_sections.py`): the deterministic critique as data (kv / note-with-tone / table); `cli.render_report` renders the same sections as text, so the CLI and the run page stay in sync. Keep it defensive: five stored runs have `legs: null`, empty `error_shape` and null stream velocities, and used to crash the report.
- **Critiques** (`critiques.py`, `docs/critiques.md`): canonical `out/critiques/<run_id>.json`, mirrored into the index. `run_hash` covers the metrics **and the notes**; `prompt_hash` covers the system prompt; a different model is not staleness. The web streams the call as SSE; the key never leaves the server; `web.llm_remote: false` gates non-loopback clients on the LLM routes only.
- **Annotations** (`annotations.py`, `docs/annotations.md`): canonical sidecars `out/annotations/<beatmap_md5>.json`, mirrored into the index on every sweep. `t_map` is **seconds in map time**; object `t` is row-clock milliseconds — convert with `time_base.rows_scale` (`to_map_time`/`to_row_ms`). `coach`/`prompt` read them; `report` does not. The web forms need `python-multipart`.
- **Boards** (`web/boards.py`, `docs/web.md`): per-run near-miss windows + playfield overview + cleanest stretch, computed from `autopsy.misses.rows` and the object positions, drawn client-side on canvas. Keep it out of the request path: the panel is a collapsed `<details>`.
- **Web** (`web/app.py`, `web/data.py`, `covers.py`, `docs/web.md`): FastAPI + Jinja2 + htmx, optional extra `[web]`. Second frontend only — it imports the library and reads the index, never recomputes a metric. Pages live in `web/templates/`, the whole client script is `web/static/app.js` (two canvases + one lazy table), and `tests/test_web.py` drives every route through `TestClient`.

## Conventions and traps

Read `docs/ROADMAP.md` before changing analysis code; it records the mistakes already made.

- `snap` is in **quarter-beats**: the divisor is `4 / snap`. Use `profile.divisor()` / `beats_label()`, and always print the real ms gap next to a label.
- Convert ms to the player's time base before quoting numbers for RX/Relax; keep `window_ms` explicit in output.
- Row indices are **object indices**, not filtered-row indices (an earlier autopsy bug mis-mapped rows this way).
- Legs shorter than ~1.5 circle radii have no meaningful direction; filter on the gap in radii, not pixels.
- Population gates scale with map size: `min(20, max(8, 3% of objects))`. Never state a rate from n<10, and quote n with every rate.
- Findings should come from contrasts (same map across attempts, shapes with corners vs without), not absolute numbers.
- New features need new fixtures in `tests/fixtures/`. Synthetic fixtures are regenerated by `scripts/make_synthetic_fixtures.py`; real replays are anonymized (`TestPlayer`) and credited in `tests/fixtures/ATTRIBUTION.md`.
- **The index is a projection, never a source of truth.** Deleting `out/index.sqlite` loses nothing; annotations and critiques are the only authored data and they live in sidecar files under `out/`. `replay_md5` is the replay's internal hash, not the `.osr` file's md5 (verified 0/383), so a historical `replay_path` needs an explicit parse pass; `beatmaps.map_path` is the resolvable map file. `is_relax` means RX **or** AP **or** `aim_mode.is_relax`.
- Git: this machine has no global identity. Commits and annotated tags need `-c user.name="ran" -c user.email=id+ranelb@users.noreply.github.com`. Push to `main`.
- The web layer's traps: `render()` must pass `status_code=` (a 404 otherwise renders 200); the listing reads `rank_status`, not `status`; the trust banner's wording must differ, not just its class; cover fetches are lazy per `<img>` so a listing render never makes 792 HTTP requests.
