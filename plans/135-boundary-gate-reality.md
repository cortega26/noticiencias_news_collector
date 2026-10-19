# Plan 135: Make `make test-boundaries` a gate that can actually fail

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- Makefile tests/unit/system/test_d1_pipeline_boundaries.py news_collector/system/ docs/AGENTS.md docs/ci.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M (there is an approved S-sized fallback in Step 3)
- **Risk**: LOW
- **Depends on**: none (do not run concurrently with plans 138/139/143/144/145 — shared Makefile/CI)
- **Category**: tests
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

`docs/AGENTS.md` §10 makes `make test-boundaries` the **minimum validation for
any orchestration, workflow, collector, storage, or serving change**, and
`make verify-ci` runs it as the canonical CI gate (`docs/ci.md:10`). Today that
target runs exactly one file with three tests, all against `MagicMock`
collaborators, and the third test ends with a comment instead of an assertion
("If it didn't crash (ValidationError), the adapter worked."). A reviewer who
sees `verify-ci` green for a serving/storage change has been told a boundary
contract was verified when nothing boundary-shaped was asserted. Two of the
three tests also assert on a *fake's* call arguments, which `docs/AGENTS.md`
§4.1 rule 3 explicitly rejects ("Assert on the fakes").

## Current state

- `Makefile:299-301`:

```make
test-boundaries: bootstrap ## Run D1 System Boundary tests (Behavior only, no coverage)
	@echo "[test-boundaries] Verifying System Boundaries (D1 Phase 2)..."
	@PYTHONPATH=$(CURDIR) $(PYTEST) tests/unit/system/test_d1_pipeline_boundaries.py --no-cov
```

- `Makefile:249` — the target is inside `verify-ci`.
- `tests/unit/system/test_d1_pipeline_boundaries.py` — 3 tests:
  - `:56 test_export_boundary_uses_contract` — asserts the export dict's
    `contract`/`version`/`article_count` fields (this one has real assertions, but
    the DB is a `MagicMock` returning a hand-built fake ORM object).
  - `:72 test_validation_boundary_uses_payload` — asserts on
    `mock_system.validator.validate_batch.call_args` (a fake's call args).
  - `:93 test_scoring_boundary_uses_input_model` — ends at `:120` with
    `# If it didn't crash (ValidationError), the adapter worked.` and no assertion.
- The mock fixture is `NewsCollectorSystem()` with `db_manager`, `validator`,
  `scorer`, `logger` all `MagicMock` (`:13-21`).

Repo rules that apply: AGENTS §4.1 (a test earns its place when it can fail for a
real reason; mock only at boundaries: network, LLM, clock, filesystem outside
`tmp_path`; real SQLite preferred). LAW-B1/B2 (typed boundaries; adapters are the
only shape-conversion point) define what "boundary" means here.

## Commands you will need

| Purpose          | Command                                                             | Provenance | Expected on success          |
|------------------|---------------------------------------------------------------------|------------|------------------------------|
| Install/baseline | `make bootstrap`                                                    | declared   | exit 0                       |
| Lint             | `make lint`                                                         | declared   | exit 0                       |
| Types + coverage | `make type`                                                         | declared   | exit 0                       |
| Boundaries       | `make test-boundaries`                                              | declared   | exit 0, N tests collected    |
| Unit suite       | `make test`                                                         | declared   | all pass                     |
| Contracts        | `make test-contracts`                                               | declared   | exit 0                       |
| Ledger           | `make plans-ledger-check`                                           | declared   | `validate_plans_ledger: OK`  |

Provenance: all `declared` (advisor read the `Makefile`; the suite was not run).
A `declared` command failing on an unmodified checkout is a broken baseline —
STOP and report.

## Scope

**In scope**:

- `tests/unit/system/test_d1_pipeline_boundaries.py` (rewrite the three tests)
- `tests/unit/system/` — new helper fixtures if needed
- `Makefile` — only the `test-boundaries` recipe, and only if Step 3 is taken
- `docs/AGENTS.md` §10 (and §5.1 prose if it names the target) — only if the
  gate's meaning changes
- `docs/ci.md` — only if the gate's meaning changes

**Out of scope** (do NOT touch):

- `news_collector/system/**` — behavior must not change; this plan changes only
  tests (and, in the fallback, the target's name/meaning).
- Any other Makefile target (plans 138/139 own those).
- Coverage ratchet files.

## Git workflow

- Branch: `advisor/135-boundary-gate-reality`
- Conventional commits, e.g. `test(system): assert real boundary contracts in the boundary gate (plan 135)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, then the remaining table commands on the unmodified
checkout. Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Decide which way this gate goes (choose ONE, record the choice)

- **Option A (preferred — real boundary assertions).** Keep the target name and
  the three scenarios, but drive them with real collaborators where the boundary
  is the subject: a real SQLite `DatabaseManager` (the fixtures in
  `tests/test_serving_admin_api.py:27-40` show the pattern) and real contract
  models; mock only the network/LLM edges. Assertions must be about the payload
  **shape** crossing the boundary (e.g. the object passed to the validator
  validates as `ArticleValidationPayload`, and a deliberately malformed payload is
  rejected with a typed error), not about mock call counts.
- **Option B (fallback — honest demotion).** If Option A cannot be built within
  ~1 day (see the STOP rule in Step 3), rename the file to
  `tests/unit/system/test_smoke_pipeline_wiring.py`, rename the target to
  `test-wiring-smoke`, and change `docs/AGENTS.md` §10 to require the **real**
  targeted suites for boundary changes (`make test`, `make test-contracts`, and
  the module's own integration tests). Update `docs/ci.md:10` accordingly. The
  gate must stop claiming to verify boundaries it does not verify.

Record the choice and the reason at the top of the test file's module docstring.

**Verify**: your decision is written down before you edit tests.

### Step 2: Implement the chosen option

For **Option A**:

1. Build the three tests against real collaborators:
   - export boundary → real DB + real adapter path, assert the produced document
     validates against `news_collector.contracts`' export model (find it where
     `export_latest_articles` builds it) and that `article_count` matches the
     rows you inserted;
   - validation boundary → assert the payload object handed to the validator
     **is** the typed model (not a bare dict) and that an invalid item yields the
     documented per-item outcome (LAW-B6), not a crash;
   - scoring boundary → assert deterministic ordering of the page returned by
     `get_pending_articles_page`/`get_completed_articles_for_rescoring_page` with
     real rows (LAW-B10 determinism), replacing the assertion-free test.
2. Every test must contain at least one assertion **and** must fail if the
   boundary type is changed to a raw `dict` (prove at least one of them by
   temporarily violating it).

**Verify**: `.venv/bin/pytest tests/unit/system/test_d1_pipeline_boundaries.py -q --no-cov` → all pass; then *temporarily* break the type in a scratch copy and confirm the test fails (revert the scratch change).

### Step 3: Escalate rather than sprawl

If, after ~1 day of work, Option A still requires mocking half the system (the
`NewsCollectorSystem` constructor pulls real collaborators — see
`news_collector/system/__init__.py`), **stop pursuing the rewrite**, take Option B
instead, and say so in the ledger row. Do not extend the plan to a
`NewsCollectorSystem` refactor.

**Verify**: `make test-boundaries` (or the renamed target) exits 0 with a
recorded test count > 0.

### Step 4: Keep the docs truthful

- Option A: no doc change needed.
- Option B: update `docs/AGENTS.md` §10 row for "Orchestration, workflow,
  collector, storage, or serving change" and §5.1's target list, plus
  `docs/ci.md`'s gate description.
- Either way run `make docs-check` and `make docs-review` and include the output.

**Verify**: `make docs-check` → exit 0; `grep -n "test-boundaries\|test-wiring-smoke" docs/AGENTS.md docs/ci.md Makefile` → consistent.

## Test plan

- The three rewritten tests are themselves the deliverable; plus at least one
  negative case per boundary (invalid payload → typed error, not a crash).
- Keep running time under ~30 s (`make test-boundaries` currently runs in
  seconds; a real SQLite fixture is fast enough).

**Verify**: `make test && make test-boundaries` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test` exit 0
- [ ] `make test-boundaries` exits 0 and **every** collected test contains an assertion
      (paste `pytest --collect-only -q` count and a grep for `assert` per test in the ledger row)
- [ ] At least one new test provably fails when a boundary type is replaced with a raw dict
- [ ] Makefile/AGENTS/docs describe the gate accurately (diff shown)
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 135 updated; `make plans-ledger-check` → OK

## STOP conditions

- The excerpts do not match the live code (drift).
- Option A requires changing `news_collector/system/` behaviour to be testable —
  that is a refactor, not a test, and belongs in a new plan (report it).
- `make test-boundaries` is referenced by anything else you did not expect
  (`grep -rn "test-boundaries" .github/ docs/ scripts/ Makefile`) — report before
  renaming.

## Maintenance notes

- The value of this gate is that it fails when a *shape* changes. If a future
  change adds a new boundary, add a case here rather than a new target.
- Reviewer should scrutinise: no `MagicMock` is used as the subject of an
  assertion; the DB fixture is real (`tmp_path`), and the tests are order-safe
  (they will run under `pytest-randomly`).
- **Deferred:** coverage instrumentation for this target (it runs `--no-cov`
  deliberately; plan 137's full-profile work may change that). Unblocked by 137.
