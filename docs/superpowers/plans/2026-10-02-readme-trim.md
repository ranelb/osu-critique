# README Trim & Re-home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the README to a lean front door (Quickstart directly below the table of contents) by moving detail into four new `docs/` files, without losing a single fact.

**Architecture:** Create the destination docs first (copy the content verbatim), then strip the source blocks from `README.md` and replace each with a one-to-three-line summary plus a link. Nothing under `src/` changes; the test suite and CI matrix are untouched.

**Tech Stack:** Markdown only. `pytest` is the regression gate (docs changes must not break the suite).

**Spec:** The user's instruction on 2026-10-02 — "trim (with plan), look at what can be removed and put into docs, and finally put quickstart further up … optimally right below ToC" — plus the health-review findings in `~/.local/share/ryoku/rashin/journal/2026-10-02.md` ("osu-critique health review" and "osu-critique health fixes landed"). The diagnosis: the `### Supported LLM` heading carries ~562 words of metrics that are not about the LLM, and the `Commands` block duplicates prose from above.

## Global Constraints

- **No content loss.** Every removed block must exist, verbatim or better, in one of the new docs before the README block is deleted. Deleting a fact is a defect, not a trim.
- **Docs-only.** `src/`, `tests/`, `pyproject.toml`, `.github/` are not touched. `pytest -q` must stay `138 passed, 6 skipped`.
- **Exact values are already correct** — keep `0.10.1`, `144 tests (138 run anywhere; 6 skip …)`, `CI on Python 3.10-3.14`, and the `v0.10.1` wheel URL as they now are.
- **Quickstart goes immediately after the Table of Contents**, before Features.
- Public repo: never commit `out/`, `tmp_maps/`, or unanonymized `.osr`.
- Commits need identity: `git -c user.name=ran -c user.email=id+ranelb@users.noreply.github.com commit -m "<msg>"`.
- Existing docs to link, not duplicate: `docs/aim.md`, `docs/autopsy.md`, `docs/profile.md`, `docs/object_schema.md`, `docs/ROADMAP.md`.

## Review Focus

- **A moved fact silently dropped** — the trim's central risk. Every destination doc gets a sentinel check (Task 6) naming strings that must survive.
- **Quickstart not actually first** — verify by reading the heading order, not by trusting the edit.
- **Broken relative links** — every `docs/*.md` the README references must exist; check with `test -f`/`ls`, not by eye.
- **ToC anchors that no longer match headings** — GitHub slugs from the real heading text (`## Quickstart` → `#quickstart`); regenerate the list from the final headings.
- **The README re-bloating as the docs shrink** — the point is a lean front door; if a summary section grows past a few lines it should link, not explain. Target ≤ ~2,200 words (from 3,327).

---

## File Structure

- **Create** `docs/metrics.md` — the full per-play metrics catalogue (today's README lines 77-132).
- **Create** `docs/configuration.md` — first-time setup wizard + path detection + the env-var table (README 167-198, 261-302).
- **Create** `docs/internals.md` — the ten-step pipeline (README 303-341).
- **Create** `docs/trust.md` — validation & trust + edge cases/limitations (README 343-392).
- **Rewrite** `README.md` — Quickstart under the ToC; condensed Features / Commands / Configuration / How it works / Validation / Limitations.

Source line numbers below are the state at plan time (commit `d7a2ca4`) and stay stable through Tasks 1-4, because those tasks only create files. Task 5 edits `README.md` last.

---

### Task 1: `docs/metrics.md` — the per-play metrics catalogue

**Files:**
- Create: `docs/metrics.md`
- Source: `README.md:77-132`

**Interfaces:**
- Consumes: nothing.
- Produces: the link target `docs/metrics.md` that Task 5's Features section points at.

- [ ] **Step 1: Create the file from the moved block**

Write `docs/metrics.md` with:
- an H1 `# Per-play metrics`, a two-line intro ("everything `analyze` writes into `out/<tag>_metrics.json`; the per-object schema is `docs/object_schema.md`"), then
- the list from `README.md` lines 77-132 **verbatim** — from `Per-play metrics include:` through the `- **Flags**: ...` bullet. Preserve every bullet and every inline value (`n-gated`, `±320 ms`, `MONTAGEM`, `0 segments before, 19 now`, etc.).
- a closing "See also" linking `docs/aim.md`, `docs/autopsy.md`, `docs/profile.md`, `docs/object_schema.md`.
- Keep the `docs/...` links already inside those bullets working (they are relative to `docs/`, so `[docs/aim.md](docs/aim.md)` becomes `[aim.md](aim.md)` — resolve every link so it points from within `docs/`).

- [ ] **Step 2: Verify the moved block is present and links resolve**

Run:
```bash
grep -c "^- \*\*" docs/metrics.md          # bullet count matches README 77-132
grep -n "Two clocks\|Rolling baselines\|Cross-attempt structure\|Whiffs by cause\|Aim ceiling\|Map profile\|Flags" docs/metrics.md
grep -oE '\]\([^)]*\)' docs/metrics.md
```
Expected: bullet count matches; all seven sentinel groups present; every link target is either an existing file (`ls docs/`) or an http(s) URL.

- [ ] **Step 3: Commit**

```bash
git add docs/metrics.md
git -c user.name=ran -c user.email=id+ranelb@users.noreply.github.com \
  commit -m "docs: move the per-play metrics catalogue into docs/metrics.md"
```

---

### Task 2: `docs/configuration.md` — setup, paths, env vars

**Files:**
- Create: `docs/configuration.md`
- Source: `README.md:167-198` (first-time setup) and `README.md:261-302` (configuration + paths + env table)

**Interfaces:**
- Consumes: nothing.
- Produces: the link target `docs/configuration.md`.

- [ ] **Step 1: Create the file from the two moved blocks**

Write `docs/configuration.md` with an H1 `# Configuration`, then:
- the setup-wizard block (`## First-time setup`, README 167-198) verbatim — including the wizard transcript, the `0600` note, `setup --show`, the model override, and the precedence line.
- the settings + path block (README 261-302) verbatim — the precedence sentence, the platform-probe table, and the full env-var table (every `OSU_*` row, including `OSU_MEMORY_LIMIT_GB` and `OSU_ALLOW_SCRAPE`).
- Fix the one heading level collision: both blocks were H2 in the README; make the setup block `## First-time setup` and the settings block `## Paths and environment` (or similar) under the single H1.

- [ ] **Step 2: Verify**

Run:
```bash
grep -c "^| \`OSU_" docs/configuration.md
grep -n "OSU_MEMORY_LIMIT_GB\|OSU_ALLOW_SCRAPE\|osu!stable\|0600\|config.json" docs/configuration.md
```
Expected: 18 env rows (the README table has 18 `| \`OSU_…` rows); all five sentinels present.

- [ ] **Step 3: Commit**

```bash
git add docs/configuration.md
git -c user.name=ran -c user.email=id+ranelb@users.noreply.github.com \
  commit -m "docs: move setup, paths and env vars into docs/configuration.md"
```

---

### Task 3: `docs/internals.md` — the pipeline

**Files:**
- Create: `docs/internals.md`
- Source: `README.md:303-341`

**Interfaces:**
- Consumes: nothing.
- Produces: the link target `docs/internals.md`.

- [ ] **Step 1: Create the file from the moved block**

Write `docs/internals.md` with an H1 `# How it works`, then the ten numbered steps from README 303-341 verbatim (Parse → Frames → Judgement → Calibration → Metrics → Cursor arrival → Miss autopsy → Slider bodies → Records → Tiers). Keep the two inline doc links, rewriting them to resolve from `docs/` (`docs/aim.md` → `aim.md`, `docs/autopsy.md` → `autopsy.md`).

- [ ] **Step 2: Verify**

Run:
```bash
grep -cE "^[0-9]+\. \*\*" docs/internals.md
grep -n "Calibration\|mod-adjusted\|slider" docs/internals.md
```
Expected: 10 numbered steps; sentinels present.

- [ ] **Step 3: Commit**

```bash
git add docs/internals.md
git -c user.name=ran -c user.email=id+ranelb@users.noreply.github.com \
  commit -m "docs: move the analysis pipeline into docs/internals.md"
```

---

### Task 4: `docs/trust.md` — validation and limitations

**Files:**
- Create: `docs/trust.md`
- Source: `README.md:343-392` (validation + edge cases)

**Interfaces:**
- Consumes: nothing.
- Produces: the link target `docs/trust.md`.

- [ ] **Step 1: Create the file from the two moved blocks**

Write `docs/trust.md` with an H1 `# Validation, trust and limitations`, then:
- `## Validation and trust` — README 343-367 verbatim (the 55-replay / 14-exact / L1 1470 result, the `EDGE_GUARD_MS` 1 ms guard story, the `trust` block: `count_deltas`, `within_tolerance`, `notes`).
- `## Edge cases and limitations` — README 369-392 verbatim (Relax, slider head-only, mods, lazer time convention, `map_version_mismatch`, mod flags).

- [ ] **Step 2: Verify**

Run:
```bash
grep -n "EDGE_GUARD_MS\|L1 1470\|within_tolerance\|map_version_mismatch\|judged by their head" docs/trust.md
```
Expected: all five sentinels present.

- [ ] **Step 3: Commit**

```bash
git add docs/trust.md
git -c user.name=ran -c user.email=id+ranelb@users.noreply.github.com \
  commit -m "docs: move validation, trust and limitations into docs/trust.md"
```

---

### Task 5: Rewrite `README.md` — Quickstart up, sections condensed

**Files:**
- Modify: `README.md` (full-file restructure)

**Interfaces:**
- Consumes: `docs/metrics.md`, `docs/configuration.md`, `docs/internals.md`, `docs/trust.md` from Tasks 1-4.
- Produces: the final README shipped to readers.

The final heading order must be exactly:

```
# osu-critique
## Table of Contents
## Quickstart
## Features
## Commands
## Configuration
## How it works
## Validation and trust
## Limitations
## Development
## Roadmap
## Privacy, attribution, and terms
## License
```

- [ ] **Step 1: Trim the intro and reorder the ToC**

- Keep the title, the one-line description, and a **short** status (2-3 sentences: "0.10.1 · 144 tests · CI 3.10-3.14 · fully local core"). Move the long "Presses are resolved … golden fixtures …" sentence into `docs/trust.md` if it is not already implied there; do not lose the claim.
- Regenerate `## Table of Contents` as the bullet list of the headings above, in that order.

- [ ] **Step 2: Insert `## Quickstart` immediately below the ToC**

Use exactly this content (wording is the user's priority):

````markdown
## Quickstart

Requires Python ≥ 3.10.

```sh
git clone <repo-url> && cd osu-critique
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[charts]"          # core + matplotlib for --charts
```

Replays and maps are found automatically from **osu!lazer** (Windows, Linux
Flatpak/AppImage, macOS), **osu!stable** (Windows), or the repo's `replays/` +
`maps/` folders (`.osr` / `.osu` / `.osz`; archives are unpacked). Then:

```sh
osu-critique batch --charts         # pair + analyze every replay
osu-critique report out/            # deterministic critique — no keys, no network
```

That is the core loop. Optional extras, all bring-your-own-key:

- `osu-critique setup` — ~30-second wizard for keys and non-standard paths.
- `osu-critique coach out/` — AI critique via one LLM API call.
- `osu-critique profile <username>` — osu! profile stats for context.

No git? Install the wheel from the latest release:

```sh
pip install https://github.com/ranelb/osu-critique/releases/download/v0.10.1/osu_critique-0.10.1-py3-none-any.whl
```

See [Commands](#commands) for every command, or run `osu-critique --help`.
````

- [ ] **Step 3: Condense `## Features` and remove the mislabelled metrics block**

- Keep the tier table (`Core` / `Report` / `Coach` / `Profile`).
- Keep a compact "three ways" paragraph or table (`report` / `coach` / `prompt`) — do not restate the Commands block.
- Replace the entire `### Supported LLM` section (README 69-133) with **two sentences** on the tested model (`DeepSeek V4 Flash`, default, others untested) and **one sentence + link** for metrics: "Per-play metrics — timing, aim (press and cursor arrival), miss autopsy, slider bodies, two clocks, rolling baselines, cross-attempt structure, patterns, streams, tapping, sections, whiffs, map profile, trust — are catalogued in [docs/metrics.md](docs/metrics.md)."

- [ ] **Step 4: Condense `## Commands`**

- Keep the command code block (it is the practical reference).
- Delete the inline `#` comments that duplicate earlier prose (`--history` lines, the `attempts` explanation, the `--scrape` explanation); keep only a short trailing phrase per command where it adds something the command name does not.
- Delete `### Quick example` (subsumed by Quickstart).
- Delete the `Output: …` paragraph (README 243-252); its facts already live in `docs/object_schema.md` and `docs/aim.md`/`docs/autopsy.md`. If any specific filename list is not covered there, add it to `docs/object_schema.md` in this step rather than dropping it.

- [ ] **Step 5: Replace Configuration / How it works / Validation / Edge cases with summaries + links**

- `## Configuration` → 3-4 lines: precedence (`env > config file > auto-detection > default`), that `setup` collects keys/paths, that `paths` prints the resolved paths, and "Full tables: [docs/configuration.md](docs/configuration.md)."
- `## How it works` → 3-4 lines naming the pipeline's shape (parse → judge in press order with mod-adjusted windows → calibrate → measure → write records) and "Full pipeline: [docs/internals.md](docs/internals.md)."
- `## Validation and trust` → one tight paragraph (judged against the game's recorded counts; the 1 ms edge guard; the `trust` block refuses to overstate) + "Full detail: [docs/trust.md](docs/trust.md)."
- `## Limitations` (renamed from `## Edge cases and limitations`) → 3 bullets (Relax, sliders head-only, mod-time quirks) + "Full list: [docs/trust.md](docs/trust.md)."

- [ ] **Step 6: Verify the README shape and length**

Run:
```bash
grep -n "^#\{1,3\} " README.md
wc -w README.md
for f in docs/metrics.md docs/configuration.md docs/internals.md docs/trust.md; do test -f "$f" && echo "ok $f" || echo "MISSING $f"; done
```
Expected: heading order matches the list above (Quickstart line is the first `##` after the ToC); `wc -w` ≤ 2200; all four `ok`.

- [ ] **Step 7: Commit**

```bash
git add README.md
git -c user.name=ran -c user.email=id+ranelb@users.noreply.github.com \
  commit -m "docs(readme): Quickstart under the ToC; move metrics/setup/pipeline/trust detail into docs/"
```

---

### Task 6: Acceptance — nothing lost, everything links

**Files:** none modified — verification only.

- [ ] **Step 1: Sentinel sweep (facts that left the README must exist in a doc)**

Run:
```bash
git show HEAD~1:README.md > /tmp/readme-before.md   # HEAD~1 = pre-trim README
for s in "EDGE_GUARD_MS" "OSU_MEMORY_LIMIT_GB" "OSU_ALLOW_SCRAPE" "osu!stable" \
         "within_tolerance" "Rolling baselines" "Cross-attempt structure" \
         "Whiffs by cause" "Aim ceiling" "Map profile"; do
  printf '%-28s before=%s  after=%s\n' "$s" \
    "$(grep -rl "$s" /tmp/readme-before.md docs/ 2>/dev/null | wc -l)" \
    "$(grep -rl "$s" README.md docs/ 2>/dev/null | wc -l)"
done
```
Expected: every row `after ≥ 1` (each fact survives somewhere). The `before` count is context, not a gate.

- [ ] **Step 2: Every README link resolves**

Run:
```bash
grep -oE '\]\([^)#]+\.md\)' README.md | tr -d '](）' | sort -u | while read p; do [ -f "$p" ] && echo "ok $p" || echo "BROKEN $p"; done
```
Expected: no `BROKEN`.

- [ ] **Step 3: Heading order gate (Quickstart is first after ToC)**

Run:
```bash
grep -n "^## " README.md | head -4
```
Expected: `Table of Contents`, then `Quickstart`.

- [ ] **Step 4: Suite still green, then push**

Run:
```bash
.venv/bin/python -m pytest -q
git push origin main
gh run list --branch main --limit 1
```
Expected: `138 passed, 6 skipped`; push accepted; the new CI run goes green on 3.10/3.12/3.14 (docs-only, but the gate is the same).

---

## Self-Review

**Spec coverage:** trim (Task 5) ✓; "what can be removed, put into docs" (Tasks 1-4 create the four destinations; Task 5 removes the sources) ✓; "quickstart further up, optimally right below ToC" (Task 5 Steps 2 and 6) ✓; no content loss (Global Constraints + Task 6 Step 1) ✓; broken-link and anchor risk (Task 6 Steps 2-3) ✓.

**Step scan:** each step names the source range or the exact text; the only verbatim block is Quickstart, whose wording the user singled out. No step says "tidy up" or leaves a destination unnamed.

**Type/naming consistency:** the four doc paths are identical in Tasks 1-4, Task 5's link checks, and Task 6. The heading order list in Task 5 Step 1 matches the `grep -n "^## "` expectation in Task 6 Step 3. The `HEAD~1` in Task 6 assumes Task 5 is the last commit — true by ordering; if Task 5 is split into more commits, use the merge-base instead.

**Review Focus coverage:** dropped fact → Task 6.1; Quickstart position → Task 5.6 / Task 6.3; broken links → Task 6.2; ToC anchors → Task 5.1 + Task 6.3; re-bloat → the ≤ 2,200-word gate in Task 5.6.

**Proportion:** the plan decides what moves where and which summaries stay; it does not rewrite the moved prose (those blocks are copied, not authored). No `src/` change, no new tests.
