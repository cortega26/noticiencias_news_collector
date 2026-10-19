# Plan 166: Make `make quality` and the bootstrap stamp tell the truth

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat cdee85f6..HEAD -- Makefile scripts/editorial_critic_canary.py`
> If either file changed since this plan was written, re-read it before editing;
> on a mismatch with the excerpts, STOP.

## Status

- **Priority**: P2 (two gates that lie)
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 154 (canary), 156 (security-lock split)
- **Category**: build / security gate
- **Planned at**: commit `cdee85f6`, 2026-10-19

## Why this matters

Two local gates are red/lying while CI stays green:

1. **`make quality` fails** (documented safe entry point in `AGENTS.md`). Its
   Bandit leg runs without a severity filter and reports two LOW findings in
   `scripts/editorial_critic_canary.py`: **B404** (`import subprocess`, line 42)
   and **B607** (`subprocess.run(["git", ...])` with a partial path, line 269).
   CI runs `make quality-ci`, which filters Bandit to HIGH, so the failure has
   been invisible since plan 154 merged the canary. The repository already has
   the house pattern for both: annotated `nosec B404` imports with a reason, and
   `shutil.which("git")` to resolve the binary (`scripts/validate_plans_ledger.py:19,24`,
   `scripts/adversarial_review.py:32,48`).
2. **The bootstrap stamp only depends on `requirements.lock`**
   (`Makefile:71: $(BOOTSTRAP_STAMP): requirements.lock`). Plan 156 removed
   semgrep from `requirements-security.lock` and changed the runtime pins
   resolved in `.venv`, but a developer who pulled that commit keeps the old
   venv: `make lock-parity-check` then fails (observed: click 8.4.2 vs 8.5.0,
   pyee 13.0.1 vs 13.0.0, smmap 5.0.2 vs 5.0.3) until they manually delete
   `.venv/.bootstrap-complete`. CI is unaffected because its cache key includes
   the lock hashes.

## Current state

- `scripts/editorial_critic_canary.py:42` — bare `import subprocess`.
- `:267-278` — `_git_sha()` runs `subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], ...)`,
  catching `OSError`/`subprocess.SubprocessError`.
- `Makefile:71` — `$(BOOTSTRAP_STAMP): requirements.lock`; the recipe installs
  **both** `requirements.lock` and `requirements-security.lock` (`:80-81`).
- `make quality` (Makefile `quality:` target) runs
  `bandit -q -r news_collector scripts -c pyproject.toml -f txt` with no
  severity filter → exit 1 on those two LOW findings.
- `make quality-ci` filters to HIGH and is green.

## Commands you will need

| Purpose        | Command                                              | Provenance | Expected |
|----------------|------------------------------------------------------|------------|----------|
| Install        | `make bootstrap`                                     | declared   | exit 0   |
| Quality (full) | `make quality`                                       | declared   | **exit 0** |
| Quality (CI)   | `make quality-ci`                                    | declared   | exit 0   |
| Canary tests   | `.venv/bin/pytest tests/scripts/test_editorial_critic_canary.py -q --no-cov` | declared | all pass |
| Lint/types     | `make lint` / `make type` (committed tree)           | declared   | exit 0   |
| Unit suite     | `make test`                                          | declared   | all pass |
| Parity         | `make lock-parity-check`                             | declared   | exit 0   |
| Ledger         | `make plans-ledger-check`                            | declared   | OK       |

Provenance: all `declared`.

## Scope

**In scope**: `scripts/editorial_critic_canary.py`, `Makefile`.

**Out of scope**: Bandit configuration, severity thresholds, `quality-ci`,
the canary's behaviour/exit codes, any lock content.

## Steps

### Step 1: Follow the house pattern for the two findings

1. Line 42 → `import subprocess  # nosec B404 - deliberate: fixed git argv, no shell, bounded timeout`
   (match the existing wording style; keep it truthful).
2. In `_git_sha()`, resolve the binary first:
   ```python
   git = shutil.which("git")
   if git is None:
       return ""
   ```
   (import `shutil`), then use `[git, "-C", ...]` in the `subprocess.run` call.
   Keep the existing `OSError`/`SubprocessError` fallback and the empty-string
   contract (the canary reports `git_sha=""` when git is unavailable).
3. Verify the canary still behaves in both cases:
   - `tests/scripts/test_editorial_critic_canary.py` green;
   - a quick manual call of `_git_sha()` returns the current SHA with git on
     `PATH`, and `""` when `PATH` is emptied (simulate with
     `PATH=/nonexistent .venv/bin/python -c "..."` — do not change the file for
     this).

**Verify**: `make quality` exits 0; `make quality-ci` exits 0.

### Step 2: Make the stamp follow the security lock

4. `Makefile:71` → `$(BOOTSTRAP_STAMP): requirements.lock requirements-security.lock`
   (no other change to the recipe; `requirements-semgrep.lock` belongs to the
   `.venv-security` stamp and must not be added here).
5. Prove it: record `stat -c %Y .venv/.bootstrap-complete`, `touch requirements-security.lock`,
   run `make bootstrap` (long), confirm the stamp mtime changed and
   `make lock-parity-check` is green. Restore the lock's mtime is unnecessary
   (git does not track mtimes), but do **not** modify its content.

**Verify**: a security-lock change reruns bootstrap; parity green.

### Step 3: Gates

6. `make lint`, `make type` (**post-commit**), `make test`,
   `make test-contracts`, `make test-boundaries`, `make quality`,
   `make quality-ci`, `make docs-check`, `make plans-ledger-check`.

**Verify**: all exit 0.

## Done criteria

- [ ] `make quality` exits 0 (no Bandit findings)
- [ ] `make quality-ci` still exits 0; canary tests green
- [ ] `_git_sha()` returns the SHA with git and `""` without it
- [ ] `$(BOOTSTRAP_STAMP)` depends on `requirements-security.lock`; a touch reruns bootstrap
- [ ] `make lock-parity-check` green on the rebuilt venv
- [ ] `git diff --name-only main...HEAD` lists exactly the two in-scope files
- [ ] Ledger row 166 updated by the reviewer

## STOP conditions

- The canary legitimately needs a **shell** or dynamic argv (it does not today) →
  report; do not add `# nosec` to hide a real risk.
- Resolving `git` by `shutil.which` changes the evidence contract (e.g. tests
  assert the literal `"git"` string) → report and adjust only the test if it is
  purely a path assertion.
- Adding the security lock to the stamp causes bootstrap to reinstall on every
  run (check the stamp logic; if so, report).
