# osu-critique Maintenance Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the six health-review findings (documentation/version drift, CI coverage, stale local install metadata, and the privacy boundary for local artifacts) without changing any analysis behaviour.

**Architecture:** Text-only changes to `README.md`, `docs/ROADMAP.md`, and `.github/workflows/test.yml`, plus one local (uncommitted) virtualenv refresh. No file under `src/` changes; the test suite must stay at 138 passed / 6 skipped.

**Tech Stack:** Python ≥ 3.10, `numpy`, `slider==0.8.4`, `pytest`, GitHub Actions (`actions/setup-python`).

**Spec:** `~/.local/share/ryoku/rashin/journal/2026-10-02.md`, section "osu-critique health review (20:38, pi)" — the six numbered findings this plan fixes.

## Global Constraints

- `requires-python = ">=3.10"`; runtime deps are exactly `numpy>=1.24` and `slider==0.8.4` (pinned). Do not add, remove, or re-version a dependency.
- No behaviour change: `src/` is not touched by this plan. `pytest -q` must report `138 passed, 6 skipped`.
- Every version/number quoted in this plan was verified in the working tree on 2026-10-02. Do not "modernise" a value beyond what a step specifies.
- Public repo: never commit `out/`, `tmp_maps/`, the plan file itself (`docs/superpowers/`), or any unanonymized `.osr`.
- This box has no git identity. Run commits as:
  `git -c user.name=ran -c user.email=id+ranelb@users.noreply.github.com commit -m "<msg>"`
- Pushing to `main` triggers `.github/workflows/test.yml` (CI). That run is the only real gate for Task 1.

## Review Focus

- **Python 3.10 in CI may fail to resolve a dependency** (`scipy`, a transitive dep of `slider==0.8.4`, dropped older interpreters over time). If the 3.10 job cannot install or test, the correct fix is to pin the last compatible `scipy`/`numpy` in the `3.10` leg only, not to silently drop the declared floor. Task 1 owns this.
- **Rewriting the README wheel URL to a non-existent release asset** would send a user to a 404. The `v0.10.1` asset `osu_critique-0.10.1-py3-none-any.whl` is confirmed to exist; Task 2 re-confirms with `curl -sI` before/after.
- **Stale editable install metadata** (`pip show osu-critique` reports `0.1.7` while the source is `0.10.1`) makes `importlib.metadata`-based tooling lie. Task 4 owns the refresh; it is local-only and does not omit the verification.
- **Historical release notes being "fixed" by mistake**: `docs/ROADMAP.md` lines 36/288/318 mention `0.10.0` because that release shipped rolling baselines. Those are correct history and must stay. Task 3 changes only the state line (L8) and the workflow comment (L93).
- **Counts re-rotting**: the test count is now written as a relationship (total collected vs always-run vs opt-in skips) so a future reader can tell which number moved. Task 2 and Task 3 use the same wording.

---

## File Structure

- `.github/workflows/test.yml` — CI matrix (Task 1).
- `README.md` — status/version, install-from-release example, test count, CI matrix mention, the Development command comment; duplicate heading removed (Task 2).
- `docs/ROADMAP.md` — the handoff state line + the working-method test-count comment; one explicit privacy line in the traps list (Task 3).
- `.venv/` — local only, gitignored (Task 4). No committed file.
- `docs/superpowers/plans/2026-10-02-maintenance-health-fixes.md` — this plan; keep untracked.

---

### Task 1: CI Python matrix (issue 4)

**Files:**
- Modify: `.github/workflows/test.yml:12,17`

**Interfaces:**
- Consumes: nothing.
- Produces: the exact CI interpreter set the README and ROADMAP must quote in Task 2 and Task 3: **3.10, 3.12, 3.14**.

- [ ] **Step 1: Change the matrix and the action version**

Edit `.github/workflows/test.yml`. The final content must contain:

```yaml
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ matrix.python-version }}
```

and the matrix line becomes:

```yaml
        python-version: ["3.10", "3.12", "3.14"]
```

Leave `actions/checkout@v4` and everything else unchanged. `setup-python@v7` supports 3.14 (verified in the action's own e2e workflow).

- [ ] **Step 2: Verify the diff is exactly those two lines**

Run: `git diff --stat .github/workflows/test.yml && git diff .github/workflows/test.yml`
Expected: one file, 2 changed lines (`setup-python@v5`→`@v7`; `["3.11","3.12"]`→`["3.10","3.12","3.14"]`). No other hunk.

- [ ] **Step 3: Confirm the workflow YAML parses**

No `pyyaml`/`actionlint` is installed. Parse with the venv:

Run: `.venv/bin/pip install pyyaml -q && .venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml')); print('yaml ok')"`
Expected: `yaml ok`. (`pyyaml` is a throwaway check tool; do not add it to `pyproject.toml`.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/test.yml
git -c user.name=ran -c user.email=id+ranelb@users.noreply.github.com \
  commit -m "ci: test the declared 3.10 floor and the 3.14 runtime; setup-python v7"
```

- [ ] **Step 5: Push and verify all three jobs pass**

Run: `git push origin main`
Then open the Actions run for the pushed commit (or `gh run watch`) and confirm three green jobs: 3.10, 3.12, 3.14.
Expected: all three green. **If the 3.10 job fails on dependency resolution**, resolve it inside this task by adding a `3.10`-only constraint (e.g. `pip install "numpy<2.3" "scipy<1.16"` in an `if: matrix.python-version == '3.10'` step), then re-push. Do not remove 3.10 and do not change `requires-python`.

---

### Task 2: README accuracy (issues 1, 2, 3 + CI text from issue 4)

**Files:**
- Modify: `README.md` (lines 11, 15–16, 148, 157, 162, 368/370, 399, 419)

**Interfaces:**
- Consumes: the CI set from Task 1 (`3.10, 3.12, 3.14`) and the verified `v0.10.1` release asset.
- Produces: the corrected wording Task 3 mirrors.

- [ ] **Step 1: Re-confirm the release asset exists before quoting it**

Run: `curl -sI https://github.com/ranelb/osu-critique/releases/download/v0.10.1/osu_critique-0.10.1-py3-none-any.whl | head -1`
Expected: `HTTP/2 302` (or `200`). If it is `404`, stop — do not rewrite the URL; report it instead.

- [ ] **Step 2: Apply the six text fixes**

In `README.md`:

1. Line 11: `> **Status: 0.10.0.**` → `> **Status: 0.10.1.**`
2. Lines 15–16: replace the fragment
   `136 tests, CI on Python\n> 3.11/3.12.`
   with
   `144 tests (138 run anywhere; 6 skip without the author's replays), CI on\n> Python 3.10-3.14.`
3. Line 148: `# → osu-critique 0.10.0` → `# → osu-critique 0.10.1`
4. Line 157: `osu_critique-0.10.0-py3-none-any.whl` → `osu_critique-0.10.1-py3-none-any.whl`
5. Line 162: `releases/download/v0.10.0/osu_critique-0.10.0-py3-none-any.whl` → `releases/download/v0.10.1/osu_critique-0.10.1-py3-none-any.whl`
6. Lines 368 and 370 are two identical `## Edge cases and limitations` headings in a row: delete one line so exactly one remains, immediately followed by the blank line and the `- **Relax replays**` bullet.
7. Line 399 (Development): `pytest -q                     # 136 tests, no network needed` → `pytest -q                     # 144 tests (6 skip without the author's replays)`
8. Line 419: `runs the suite on Python 3.11 and 3.12.` → `runs the suite on Python 3.10, 3.12, and 3.14.`

- [ ] **Step 3: Verify every drift string is gone and the heading is unique**

Run:
```bash
grep -n "0\.10\.0" README.md
grep -c "^## Edge cases and limitations" README.md
grep -n "136 tests\|3\.11/3\.12\|3\.11 and 3\.12" README.md
```
Expected: first command prints nothing; second prints `1`; third prints nothing (all three exit non-zero/zero per grep — just read the output).

- [ ] **Step 4: Commit**

```bash
git add README.md
git -c user.name=ran -c user.email=id+ranelb@users.noreply.github.com \
  commit -m "docs: README status/version 0.10.1, accurate test count, CI 3.10-3.14; drop duplicate heading"
```

---

### Task 3: ROADMAP state, test count, and privacy note (issues 3 + 6)

**Files:**
- Modify: `docs/ROADMAP.md:8,93` and the "Traps and environment quirks" bullet list (near the end)

**Interfaces:**
- Consumes: the CI set and test-count wording from Tasks 1–2.
- Produces: nothing downstream.

- [ ] **Step 1: Fix the state line (line 8) and stop pinning a commit hash**

Replace line 8 with:

```
State: **0.10.1** (tag `v0.10.1`, wheel published); 144 tests green (138 run anywhere, 6 opt-in), CI on Python 3.10/3.12/3.14 on every push, tag → wheel + GitHub release (`.github/workflows/release.yml`).
```

The old text pinned `main = 81fef6c`, which rots on every commit; the tag reference does not.

- [ ] **Step 2: Fix the working-method comment (line 93)**

`.venv/bin/python -m pytest -q                       # 136 tests, no network`
→
`.venv/bin/python -m pytest -q                       # 144 tests (6 opt-in), no network`

- [ ] **Step 3: Add the explicit artifacts/privacy line to the traps list**

In the final bullet ("**Fixtures**: ... do not put personal coaching numbers in the public repo."), append a sentence:

```
`out/` (analysis JSON/PNG) and `tmp_maps/` (extracted `.osu`) hold the author's real numbers; both are gitignored (`.gitignore:12-13`) and must never be committed.
```

- [ ] **Step 4: Verify only the intended lines changed, history intact**

Run:
```bash
sed -n '8p;93p' docs/ROADMAP.md
grep -n "81fef6c\|136 tests" docs/ROADMAP.md
grep -n "0\.10\.0" docs/ROADMAP.md
```
Expected: the two `sed` lines show the new text; `grep 81fef6c|136 tests` prints nothing; `grep 0\.10\.0` prints **only** lines 36, 288, 318 (historical release notes — correct to keep).
Also confirm the privacy boundary:
Run: `git check-ignore -v out/ tmp_maps/`
Expected: two lines, `.gitignore:12` and `.gitignore:13`.

- [ ] **Step 5: Commit and push**

```bash
git add docs/ROADMAP.md
git -c user.name=ran -c user.email=id+ranelb@users.noreply.github.com \
  commit -m "docs(roadmap): state at 0.10.1 by tag, accurate test count, explicit out/tmp_maps privacy line"
git push origin main
```

---

### Task 4: Refresh the local editable install (issue 5, no commit)

**Files:**
- Modify: `.venv/` only (gitignored).

**Interfaces:**
- Consumes: nothing.
- Produces: a venv whose package metadata matches `0.10.1`.

**Context:** `slider==0.8.4` declares `scipy` (verified in its `METADATA`), so the installed `scipy` is a legitimate transitive dependency, **not** a stray — the health note's "imported nowhere / not in pyproject" wording was wrong on this point. `setuptools` being absent is normal for a Python 3.12+ venv (build isolation fetches it). The one real defect is the stale editable metadata: `pip show osu-critique` reports `0.1.7`.

- [ ] **Step 1: Capture the stale state (before)**

Run: `.venv/bin/pip show osu-critique | grep -i '^Version'`
Expected: `Version: 0.1.7`.

- [ ] **Step 2: Re-run the editable install**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: `Successfully installed osu-critique-0.10.1`.

- [ ] **Step 3: Verify metadata, dependency graph, and tests**

Run:
```bash
.venv/bin/pip show osu-critique | grep -i '^Version'
.venv/bin/pip check
.venv/bin/python -m pytest -q
```
Expected: `Version: 0.10.1`; `No broken requirements found.`; `138 passed, 6 skipped`.

- [ ] **Step 4: Confirm the journal already carries the scipy correction**

Run: `grep -n "scipy" ~/.local/share/ryoku/rashin/journal/2026-10-02.md`
Expected: the "Correction (20:45, pi)" bullet is present (it was recorded when this plan was written). If it is absent, append it — `scipy` is a transitive dep of `slider==0.8.4`, and the editable metadata was refreshed from `0.1.7` to `0.10.1`.

- [ ] **Step 5: Confirm nothing to commit**

Run: `git status --porcelain`
Expected: empty (`.venv/` is gitignored). If it is not empty, do **not** add `.venv/`.

---

### Task 5: Whole-repo consistency sweep

**Files:** none modified — acceptance only.

- [ ] **Step 1: One pass over every file this plan touched for the same facts**

Run:
```bash
grep -rn "0\.10\.0" README.md
grep -rn "136 tests\|3\.11/3\.12\|3\.11 and 3\.12" README.md docs/ROADMAP.md
grep -n "python-version" .github/workflows/test.yml
grep -c "^## Edge cases and limitations" README.md
git status --short
```
Expected: no `0.10.0` in `README.md`; no `136 tests` or `3.11/3.12` in either doc; workflow matrix is `["3.10", "3.12", "3.14"]`; README heading count is `1`; `git status` shows only the untracked plan file (`?? docs/superpowers/`).

- [ ] **Step 2: Confirm CI is green on the pushed head**

Run: `gh run list --branch main --limit 1` (or check the Actions page)
Expected: latest `test` run = success on all three Python versions; latest `release` run unaffected.

- [ ] **Step 3: Keep the plan file untracked (or delete it)**

The plan is working scaffolding for this repo. Leave `docs/superpowers/` untracked by default; if the user prefers, delete the directory after execution. Never `git add docs/superpowers/`.

---

## Self-Review

**Spec coverage (the six findings):**
1. README version drift → Task 2, Steps 2.1–2.5.
2. Duplicate `## Edge cases and limitations` → Task 2, Step 2.6.
3. Test-count drift → Task 2 (README, Steps 2.2/2.7) + Task 3 (ROADMAP, Steps 3.1/3.2).
4. CI matrix gap → Task 1.
5. Venv reproducibility/metadata → Task 4 (with the scipy correction; env-only, no repo change).
6. Local artifacts/privacy boundary → Task 3, Step 3.3 + verification in Step 3.4.

**Type/naming consistency:** the CI set `3.10, 3.12, 3.14` and the count wording `144 tests (138 run anywhere, 6 opt-in)` are identical in Tasks 1–3 and Task 5. No function or signature is introduced, so there is nothing to mistype.

**Review Focus coverage:** each of the five failure modes in Review Focus is owned by a verification step — 3.10 resolution (Task 1 Step 5), wheel URL 404 (Task 2 Step 1), stale metadata (Task 4 Steps 1/3), historical-notes preservation (Task 3 Step 4), count re-rotting (the relationship wording, Tasks 2/3).

**Proportion:** three one-line-to-short-block doc/workflow edits and one local refresh; no new code, no tests invented. The plan decides exact strings and values; it does not transcribe a program.
