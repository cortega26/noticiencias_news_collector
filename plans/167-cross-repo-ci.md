# Plan 167: Run the cross-repo callback contract in CI (pinned frontend)

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 5876e35a..HEAD -- .github/workflows/ci.yml .gitignore tests/integration/test_publication_callback_contract.py docs/ci.md`
> If any in-scope file changed since this plan was written, read the live text
> before editing; on a mismatch with the excerpts, STOP.

## Status

- **Priority**: P1 (CI was blind to a cross-repo contract that was actually broken)
- **Effort**: S-M
- **Risk**: MEDIUM (CI dependency on another repo; keep it pinned and cheap)
- **Depends on**: frontend PR #311, merged as `7c6ad1242c6cba55e55bed6610006e78a423dd79`
- **Category**: CI / cross-repo contract
- **Planned at**: commit `5876e35a`, 2026-10-19

## Why this matters

`tests/integration/test_publication_callback_contract.py` imports the **real**
frontend sender (`../noticiencias/scripts/backend-notify.js`) and asserts that
backend correlation works. The module is skipped when the sibling checkout is
absent, which is exactly what happens in CI — so when the frontend stopped
emitting `publication_attempt_refs`, CI stayed green while the contract was
broken (articles stuck in `publishing`). The frontend fix (PR #311) is now
merged; this plan makes CI run those tests against a **pinned** frontend commit
so the contract cannot silently drift again.

## Current state

- `tests/integration/test_publication_callback_contract.py:40-52` — module-level
  `FRONTEND_REPO = Path(os.environ.get("FRONTEND_REPO_PATH", "../noticiencias")).resolve()`
  and a `pytest.mark.skipif(shutil.which("node") is None or not BACKEND_NOTIFY_SCRIPT.exists())`.
- `.github/workflows/ci.yml:211-222` — `integration` job: checkout, shared
  setup-python-env, `make test-integration`, union coverage.
- Frontend commit to pin: `7c6ad1242c6cba55e55bed6610006e78a423dd79`
  (repo `cortega26/noticiencias`, `main`).
- The sender imports only Node built-ins and `scripts/utils/*` — **no
  `node_modules` needed**. A sparse checkout of `scripts/` + `package.json`
  (`"type": "module"`) is sufficient (≈760 KB).
- Pinned actions in this repo: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1`
  (# v7.0.1) and `actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1`
  (# v7.1.0).

## Commands you will need

| Purpose            | Command                                                        | Provenance | Expected |
|--------------------|----------------------------------------------------------------|------------|----------|
| Install            | `make bootstrap`                                               | declared   | exit 0   |
| Focused tests      | `.venv/bin/pytest tests/integration/test_publication_callback_contract.py -q --no-cov -p no:randomly` | declared | 8 passed |
| Integration        | `make test-integration`                                        | declared   | all pass |
| Lint/types/tests   | `make lint` / `make type` (committed) / `make test`           | declared   | exit 0   |
| Docs/inventory     | `make docs-check` / `make inventory-check`                     | declared   | exit 0   |
| Ledger             | `make plans-ledger-check`                                      | declared   | OK       |

Provenance: all `declared`.

## Scope

**In scope**: `.github/workflows/ci.yml`, `.gitignore`,
`tests/integration/test_publication_callback_contract.py`, `docs/ci.md`.

**Out of scope**: the frontend repo (do not edit it; the pin is a commit),
`Makefile` test targets, other workflows, production code.

## Steps

### Step 1: Make the skip honest (fail closed when CI asks for it)

1. Replace the module-level `skipif` with a module-scoped autouse fixture (keep
   `pytestmark = [pytest.mark.e2e]`):
   ```python
   @pytest.fixture(scope="module", autouse=True)
   def _require_frontend_sender():
       if shutil.which("node") is None:
           pytest.skip("node is not installed")
       if not BACKEND_NOTIFY_SCRIPT.exists():
           if os.environ.get("FRONTEND_REPO_PATH"):
               pytest.fail(
                   f"FRONTEND_REPO_PATH is set but {BACKEND_NOTIFY_SCRIPT} is missing",
                   pytrace=False,
               )
           pytest.skip("sibling ../noticiencias checkout is not present")
   ```
   Rationale: a CI job that sets the path but fails to materialise the checkout
   must **fail**, not skip.
2. `.gitignore`: add `.ci/` (the CI checkout path; keep the local tree clean).
3. Verify locally:
   - without the sibling present and no env → **skipped** (simulate with
     `FRONTEND_REPO_PATH= .venv/bin/pytest ...`? That sets an empty value which is
     falsy but `os.environ.get` returns `""` — treat empty as unset; use a temp
     directory and unset the variable for the skip case);
   - with `FRONTEND_REPO_PATH=/tmp/opencode/does-not-exist` → **fails**
     (not skipped);
   - with the real sibling → 8 passed.

**Verify**: the three behaviours above.

### Step 2: Run it in the integration job against a pinned frontend

4. In `.github/workflows/ci.yml`'s `integration` job, after the backend checkout
   and before the test step:
   ```yaml
   - name: Checkout frontend sender (pinned)
     uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
     with:
       repository: cortega26/noticiencias
       ref: 7c6ad1242c6cba55e55bed6610006e78a423dd79
       path: .ci/frontend
       sparse-checkout: |
         scripts/
         package.json
       sparse-checkout-cone-mode: false
       fetch-depth: 1
       persist-credentials: false
   - name: Set up Node for the cross-repo sender
     uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
     with:
       node-version: "24"
   ```
   and on the `make test-integration` step:
   ```yaml
     env:
       FRONTEND_REPO_PATH: .ci/frontend
   ```
   Keep the coverage step unchanged.
5. **Prove the sparse checkout is enough locally** (do not trust it in CI):
   ```bash
   rm -rf /tmp/opencode/fe-sparse && mkdir -p /tmp/opencode/fe-sparse
   cd /tmp/opencode/fe-sparse && git init -q
   git remote add origin https://github.com/cortega26/noticiencias.git
   git config core.sparseCheckout true
   git sparse-checkout set scripts package.json
   git fetch -q --depth 1 origin 7c6ad1242c6cba55e55bed6610006e78a423dd79
   git checkout -q FETCH_HEAD
   ```
   then from the backend:
   `FRONTEND_REPO_PATH=/tmp/opencode/fe-sparse .venv/bin/pytest tests/integration/test_publication_callback_contract.py -q --no-cov -p no:randomly`
   → **8 passed** (no `npm install`).
6. `docs/ci.md`: document the pinned cross-repo step, that it is required on the
   integration job, and the **bump procedure**: when the frontend sender/contract
   changes, update the `ref` to the new merged frontend commit and re-run the
   focused tests.

**Verify**: YAML parses; the sparse local run passes; docs-check green.

### Step 3: Gates

7. `make test-integration` (with the local sibling present), `make lint`,
   `make type` (post-commit), `make test`, `make test-boundaries`,
   `make docs-check`, `make inventory-refresh && make inventory-check`,
   `make plans-ledger-check`.

**Verify**: all exit 0.

## Done criteria

- [ ] Missing sibling + no env → skip; env set but missing → **fail**; sibling present → 8 passed
- [ ] Integration job checks out the pinned frontend sparsely and sets `FRONTEND_REPO_PATH`
- [ ] Local sparse checkout (scripts + package.json, no node_modules) runs the 8 tests
- [ ] `.ci/` ignored; docs describe the pin + bump procedure
- [ ] `make test-integration`, lint, type, test, boundaries, docs, inventory, ledger green
- [ ] `git diff --name-only main...HEAD` lists only the four in-scope files
- [ ] Ledger row 167 updated by the reviewer

## STOP conditions

- The sparse checkout cannot run the sender (missing module) → report; broadening
  the checkout is allowed only if stated (prefer `scripts/` + `package.json`).
- The pinned frontend commit disappears from origin (force-push) → report.
- `make test-integration` becomes flaky/slow because the frontend tests now run
  in the local suite (they were already running when the sibling is present;
  report timing).
- Any need to install npm packages in the job → STOP (the sender must stay
  dependency-free).

## Maintenance notes

- The pin is deliberate: a frontend change that breaks the contract shows up when
  the pin is bumped, not silently. Bump it in the same PR that changes the
  frontend sender.
