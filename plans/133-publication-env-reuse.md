# Plan 133: Stop re-installing and rebuilding the frontend for every published article

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- news_collector/logic/workflows/publication_pipeline.py news_collector/logic/workflows/target_repo_publication.py news_collector/logic/workflows/frontend_publication_validation.py news_collector/components/publishing/github_publisher.py tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (do not run concurrently with plans 131/134 — same area)
- **Category**: perf
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

Every publication run wipes the frontend checkout (`shutil.rmtree`) and clones it
again, and then re-installs the whole npm toolchain because
`install_dependencies = not (target_dir / "node_modules").exists()` — a condition
that is **always true** for a fresh clone (`node_modules/` is gitignored in the
frontend repo, verified at `../noticiencias/.gitignore:20`). The per-article cost
is a full `npm ci` (the observed checkout is 619 MB, of which 410 MB is
`node_modules`), a `prettier --write` over the entire checkout, plus
`lint`/`validate:content`/`build`/`test:dist`/`test:audit`. Filesystem mtimes of
the last run show `.git` → `node_modules` → `dist` inside ~40 s, and this repeats
for every article and every batch item (batch is sequential, ≤ 5 ids). That is the
dominant *fixed* cost on a path that is already minutes long, and it is paid
twice when the self-repair path re-runs validation.

This plan keeps the validation gate (it is load-bearing: `reports/publish_cost_baseline.json`
records frontend validation rejecting a fraction of attempts) and only removes the
redundant re-provisioning.

## Current state

- `news_collector/logic/workflows/publication_pipeline.py:744-760` — per run:

```python
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR, ignore_errors=True)

    logger.info(f"Cloning Target Repo: {config.github.target_repo_url}")
    git_handler.clone_repo(config.github.target_repo_url, TARGET_DIR)
    target_repo_obj = git.Repo(TARGET_DIR)
```

- `news_collector/logic/workflows/target_repo_publication.py:455-470` — the
  validation call, with the always-true condition:

```python
        validation_summary = run_frontend_publication_validation(
            request.target_dir,
            summary_output_path=Path(summary_path),
            stage_fixture=False,
            post_path=request.target_dir / "src/content/posts" / output_filename,
            install_dependencies=not (request.target_dir / "node_modules").exists(),
        )
```

- `news_collector/logic/workflows/frontend_publication_validation.py:460-501` —
  the command chain: `npm ci --legacy-peer-deps` (only when
  `install_dependencies`), `publish:image-derivatives`, `prettier --write` (post,
  then the whole checkout), `lint`, `validate:content`, `build`, `test:dist`,
  `test:audit`.
- `news_collector/components/publishing/github_publisher.py:238-247` —
  `clone_repo` (full clone, no depth/filter).
- Branch/commit hygiene lives in `target_repo_publication.py` around the commit
  and push paths — read them before changing the clone step, because reusing a
  checkout must not leak item N's branch or working tree into item N+1.

Conventions: workflow code is orchestration (LAW-B3) — no policy changes; the
frontend validation gate must keep rejecting what it rejects today. LAW-B5: the
reuse must never change publication identity (slug/filename/date), only how the
checkout is provisioned. Keep logging structured (`logger.info({...})` style used
by the neighbours in these modules).

## Commands you will need

| Purpose           | Command                                                              | Provenance | Expected on success         |
|-------------------|----------------------------------------------------------------------|------------|-----------------------------|
| Install/baseline  | `make bootstrap`                                                     | declared   | exit 0                      |
| Lint              | `make lint`                                                          | declared   | exit 0                      |
| Types + coverage  | `make type`                                                          | declared   | exit 0                      |
| Unit suite        | `make test`                                                          | declared   | all pass                    |
| Boundaries        | `make test-boundaries`                                               | declared   | exit 0                      |
| Pipeline E2E      | `make test-e2e`                                                      | declared   | all pass                    |
| Focused tests     | `.venv/bin/pytest tests/unit/logic/workflows/ tests/e2e_pipeline -q --no-cov` | declared | all pass      |
| Ledger            | `make plans-ledger-check`                                            | declared   | `validate_plans_ledger: OK` |

Provenance: all `declared` (advisor read the `Makefile`; the suite was not run in
the audit session). A `declared` command failing on an unmodified checkout is a
broken baseline — STOP and report.

## Scope

**In scope**:

- `news_collector/logic/workflows/publication_pipeline.py` (target-repo provisioning only)
- `news_collector/logic/workflows/target_repo_publication.py` (the
  `install_dependencies` decision)
- `news_collector/logic/workflows/frontend_publication_validation.py` (accept a
  dependency fingerprint; keep the command chain)
- `news_collector/components/publishing/github_publisher.py` (clone/fetch helpers
  only, if needed)
- tests under `tests/unit/logic/workflows/` and `tests/e2e_pipeline/`

**Out of scope** (do NOT touch):

- The validation command list itself (lint/build/dist/audit) — do not remove or
  reorder checks.
- Batch collaborator hoisting (see `**Deferred:**` below) — a separate plan.
- Any change to identity, slug, filename, branch naming, or the commit/push path.
- `config.toml` — no new knobs in this plan.

## Git workflow

- Branch: `advisor/133-publication-env-reuse`
- Conventional commits, e.g. `perf(publication): reuse the frontend checkout between runs (plan 133)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, then the remaining table commands on the unmodified
checkout. Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Capture the before numbers

1. Time one publication attempt's frontend-validation stage on a clean checkout
   and record: total wall clock for the stage, and whether `npm ci` ran. Use the
   existing stage recorder output (`data/runtime/publication_attempts/*.frontend_validation.json`)
   as the source of truth; if you cannot run a real publish, record the
   filesystem-mtime-based estimate for `temp/target` and say it is an estimate.

**Verify**: your record exists in the plan's execution note (append it to this
file under `## Execution record`).

### Step 2: Reuse the checkout instead of wiping it

2. In `publication_pipeline.py`, replace `rmtree` + full clone with a
   reuse-first path:
   - If `TARGET_DIR` is a git repo with the expected remote: `git fetch` (the
     publisher already has a git helper — check `GitHubPublisher` for an
     existing fetch/pull primitive before adding one) and then reset the working
     tree to the remote default branch, removing untracked files **except**
     `node_modules`, `.astro`, and `dist` (a targeted `git clean -fd` on the
     tracked-content paths, never `-x` on the whole tree: `git clean -fdx` would
     delete the 410 MB we are trying to keep).
   - Else (missing/dirty beyond repair): keep today's `rmtree` + clone path.
   - Log which path was taken (`structured` log event, e.g.
     `publication.target_repo.reused` with `{"reused": true|false}`).
3. Ensure any branch/checkout state left by the previous article is reset
   before this run's branch is created. Read `target_repo_publication.py`'s
   branch creation and commit code first and confirm the reset makes it
   deterministic.

**Verify**: `.venv/bin/pytest tests/e2e_pipeline tests/unit/logic/workflows -q --no-cov` → all pass; for a two-run sequence against a local fixture remote, the second run logs `reused: true`.

### Step 3: Install dependencies only when the lock changed

4. Change the decision in `target_repo_publication.py` from
   `not (target_dir / "node_modules").exists()` to a fingerprint: compute a hash
   of `package-lock.json` (plus `package.json`) and compare it with a marker file
   written after a successful `npm ci` inside the checkout (e.g.
   `.noticiencias-npm-ci.json` holding `{"lock_sha256": ...}`), or an equivalent
   marker under `data/runtime/`. Rules:
   - No marker or hash mismatch → run `npm ci` (and write the marker on success).
   - Marker matches → skip `npm ci`.
   - The marker must live **outside** the committed tree (the frontend repo must
     not gain files that the writer could commit).
   - Verify the frontier: the writer's commit path must not stage the marker
     (check how `git add`/commit selects paths).
5. Wire the new decision through `run_frontend_publication_validation` without
   changing its behaviour when `install_dependencies=True`.

**Verify**: `.venv/bin/pytest tests/unit/logic/workflows -q --no-cov` → all pass;
a unit test asserting: fresh checkout → install; unchanged lock + marker →
skip; changed lock → install.

### Step 4: Prove the win

6. Re-run the same measurement as Step 1 (two consecutive attempts) and record
   the after numbers next to the before numbers under `## Execution record`.

**Verify**: the second attempt's stage wall clock is materially lower and
`npm ci` is absent from that stage's executed checks; both numbers are in the file.

### Step 5 (optional, only if Steps 2-4 are green): batch-level reuse

7. `run_publication_batch` (`publication_pipeline.py:817-856`) calls
   `run_publication_pipeline` once per id, which re-clones the **source** repo,
   reloads config, re-runs `preflight_llm_provider()` (a real network probe), and
   builds a new engine per item. Hoisting those per-batch is valid but wider.
   **Rule:** if this step's diff exceeds ~150 changed lines or requires touching
   more than the two workflow files already in scope, STOP after Step 4, report,
   and leave the follow-up as a new plan.

**Verify**: `.venv/bin/pytest tests/unit/logic/workflows -q --no-cov` → all pass; a 5-id batch against the local fixture runs `git clone` once (count it in logs).

## Test plan

- New unit tests in `tests/unit/logic/workflows/`:
  - reuse path chosen when the checkout exists and is clean; wipe+clone when it
    is not (both assert the log event and that the directory content survived);
  - dependency fingerprint: install / skip / re-install on lock change;
  - marker is not committed: assert the writer's staging selection excludes it
    (model after the existing writer tests, or assert on the recorded `git add`
    arguments).
- Extend `tests/e2e_pipeline/` with a two-run sequence on a local fixture remote
  proving the second run reuses the checkout and still produces the same identity
  (slug/filename/date byte-identical to the first run).

**Verify**: `make test && make test-e2e` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries`, `make test-e2e` all exit 0
- [ ] Before/after timings recorded in `## Execution record` in this file
- [ ] Two consecutive publishes produce byte-identical identity fields (prove with the e2e test)
- [ ] `npm ci` does not run on the second consecutive publish with an unchanged lock
- [ ] `git status` inside the frontend checkout after a publish is clean (no marker, no stray files)
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 133 updated; `make plans-ledger-check` → OK

## STOP conditions

- The excerpts above do not match the live code (drift) — particularly if the
  clone path already has a reuse branch.
- The writer commits with a broad `git add -A` that would pick up the marker —
  report before inventing a workaround.
- Reuse cannot be made deterministic (branch leakage, detached HEAD, or a
  `prettier --write` over a stale tree changing unrelated files).
- The e2e fixture cannot run offline in the executor's environment (report the
  exact failure rather than skipping the verification).

## Maintenance notes

- The reuse path depends on the frontend repo's default branch name and on
  `node_modules` staying gitignored there. If either changes, revisit Step 2.
- Reviewer should scrutinise: the reset sequence (no cross-article leakage) and
  that the dependency marker can never be committed.
- **Deferred:** batch-level collaborator reuse (one source clone, one config
  load, one `preflight_llm_provider`, one engine per batch). Unblocked by this
  plan landing plus a decision on engine lifecycle (plan 149 touches engine
  shutdown). Not done here to keep the blast radius small.

## Execution record

Executor: plan 133 branch `advisor/133-publication-env-reuse`, based on
`836ecc1` (worktree `/home/carlos/.local/share/opencode/worktree/62f07a/advisor-133-publication-env-reuse`).

### Step 0 — baseline (unmodified checkout)

`make lint` 0 · `make type` 0 · `make test` 0 · `make test-boundaries` 0 ·
`make test-e2e` 0. All expected results matched.

### Step 1 — before numbers (real publication attempt): NOT MEASURABLE HERE

A real publish cannot run in this worktree: it requires the LLM preflight
(Ollama/NVIDIA), a network clone of the real frontend repo, and the operator's
DB/export state. The plan's named source of truth,
`data/runtime/publication_attempts/*.frontend_validation.json`, is empty in a
fresh checkout and `temp/target` does not exist. No before-number is invented
here; the pre-change behaviour is instead pinned by the code path:
`publication_pipeline.py` wiped `temp/target` and re-cloned it for every run,
and `target_repo_publication.py` passed
`install_dependencies=not (target_dir / "node_modules").exists()` — always true
for a fresh clone, because `node_modules/` is gitignored in the frontend repo.

### Step 4 — after numbers (deterministic two-publish fixture, not a real publish)

Source: `tests/e2e_pipeline/test_publication_env_reuse_e2e.py`, which runs two
consecutive publishes through the real engine against a local fixture remote
and reports the sum of the recorded frontend-stage check durations (final
tree; a second run measured 1.031 s / 0.828 s, i.e. the wall clock moves with
machine load while the `npm ci` presence/absence does not):

| publish | frontend stage | `npm ci` |
|---|---|---|
| 1st (fresh clone, `reused: false`) | 0.983 s | 0.173 s |
| 2nd (reused checkout, `reused: true`) | 0.833 s | absent (skipped) |

Caveat: the fixture's gate is tiny (a Node stub checker), so `npm ci` is only
~20 % of its stage; the removed step is exactly `npm ci`, which the plan's
baseline records as the dominant fixed cost of the real 619 MB checkout. The
structural proof — not the wall clock — is the assertion that `npm_ci` appears
in the first stage's executed checks and is absent from the second's, with the
two publishes still producing byte-identical post bytes, filename, slug, date
and permalink.

### Step 3 refinement (deviation from the plan's bullet, disclosed)

The plan's bullet "No marker or hash mismatch → run `npm ci`" is implemented
with one carve-out: a checkout that carries `node_modules` **and** no marker
(unknown provenance) keeps the pre-plan behaviour of using the installed tree
instead of forcing an install. Reason: the pre-existing e2e harness
(`news_collector/logic/workflows/pipeline_e2e.py`, outside this plan's scope)
builds its target checkout by copying the frontend without any marker, so the
literal bullet made every e2e publish run a real `npm ci`, which fails there:

```
CHECK npm_ci success=False rc=1
  STDERR: npm error code EUSAGE | npm error | npm error The `npm ci` command can
  only install with an existing package-lock.json or npm-shrinkwrap.json ...
```

(`make test-e2e` and the focused suite went red; reproduced with
`tests/e2e_pipeline/test_pipeline_e2e.py::test_pipeline_e2e_scenarios[low_value_beats_high_value_regression]`.)

With the carve-out: fresh clone (no `node_modules`) → install + marker written;
reused checkout with a matching marker → skip; changed lock with a marker →
install; unrecorded `node_modules` → same decision as the rule this plan
replaces. The plan's own outcome therefore still holds (second publish skips
`npm ci`, e2e green); the change is confined to in-scope files. Reviewers who
prefer the literal bullet should instead authorise a marker write for the
harness's copied checkout.

### Pre-existing suite flake observed while verifying (not introduced here)

`make test` is order-flaky in this repo: with `pytest-randomly` seed
`722672841` seven unrelated tests fail (`tests/unit/collectors/test_admission.py`
× 6, `tests/security/test_ssrf_protection.py` × 1) because an earlier test
leaves a partial runtime-config snapshot in process state
(`min_content_length` falls back to 1000; `DatabaseManager()` sees a foreign
database config). Proof it is pre-existing: an unmodified snapshot of
`836ecc1` (`git archive`) run with the same explicit test order fails the same
seven tests. `make test` passed on the unmodified checkout in Step 0 with a
different seed.
