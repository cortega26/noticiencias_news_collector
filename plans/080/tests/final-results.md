# Plan 080 — Final verification and deferred decisions (V1)

Recorded 2026-10-19. Checkout base `aeaa0a76`; branch
`advisor/080-editorial-eval`. Phase 3 implementation `c15ab1ec`; Phase 3
evidence `4c562d43`; this document is committed after those. No deployment was
performed.

## Final scope

`git diff aeaa0a76..HEAD` contains only the Phase 3 allowlist plus plan
evidence:

| Area | Files |
| --- | --- |
| Development-only tool package | `tools/editorial_eval/package.json`, `package-lock.json`, `prepare.py`, `assertions.py`, `README.md` |
| Fixtures and tests | `tests/data/editorial_eval/*.jsonl`, `tests/unit/test_editorial_eval.py` |
| Entry points | `Makefile` (`editorial-eval-install`, `editorial-eval-replay`; no CI/test wiring) |
| Documentation | `docs/EDITORIAL_EVALUATION.md`, one `docs/INDEX.md` row |
| Plan evidence | `plans/080/todo.md`, `plans/080/tests/phase-3-results.md`, this file |

`git diff aeaa0a76..HEAD -- .github apps news_collector noticiencias config.toml
pyproject.toml` is empty. There are no new services, no production
schema/model/prompt changes, no DB migrations, no publication actions and no
Plan 079 changes. No generated file was repaired by hand.

## Acceptance status

Phase 4 requires honest separation of "previously recorded", "verified now" and
"not run". Phases 1–2 are already merged into the base commit; their suites were
not re-run here because Phase 3 does not touch their code.

| ID | Status | Evidence / note |
| --- | --- | --- |
| W1–W5 | **Passed previously** (not re-run) | `plans/080/tests/phase-1-results.md` at base; no workflow or storage code changed by this diff. |
| A1–A5 | **Passed previously** (not re-run) | `plans/080/tests/phase-2-results.md` at base; no admin, OpenAPI or generated TypeScript file changed by this diff. The Phase 2 `admin-contracts` CI job remains in `.github/workflows/ci.yml` and uses `npm ci` in `apps/admin`; no remote CI run was observed. |
| E1 | **Passed** | Contract/rejection tests in `tests/unit/test_editorial_eval.py`; `phase-3-results.md` E1. |
| E2 | **Passed** | Baseline 6/6, paired 7/12, exact five expected failures; public-validator exception semantics proven by unit tests. |
| E3 | **Passed** | Two offline replays produced identical 12-row outcomes; manifest hashes/provenance and per-row status inspected. |
| E4 | **Passed** | `unshare -rn` replay: only loopback, outbound probe denied, echo-only provider, exact `response.output == logged_output`. |
| E5 | **Passed for documentation/reproduction; reviewer confirmation pending** | README/docs commands reproduce the result; no production gate weakened. |
| V1 | **Pending fresh review** | All phase-3 required commands were run and recorded below. Two known non-green repository gates remain: pre-existing raw Bandit findings in `make quality`, and generated inventory drift in `make inventory-check` (outside the allowlist). The reviewer must dispose of both and confirm no material gap. |

Program-level deferred items were **not** implemented: OpenTelemetry,
Retraction Watch, Pagefind, DBOS and Sentence Transformers. Their decision gates
remain in `plans/080/04-verification-and-deferred.md`; no dependency was added.

## Commands and outcomes

| Command | Status | Observed result |
| --- | --- | --- |
| `.venv/bin/python -m pytest tests/unit/test_editorial_eval.py tests/unit/editorial/test_generated_article_guardrails.py --no-cov -q` | **Passed** | 37 passed, 1 skipped (opt-in real Promptfoo test) |
| `EDITORIAL_EVAL_PROMPTFOO_INTEGRATION=true .venv/bin/python -m pytest tests/unit/test_editorial_eval.py::test_real_promptfoo_baseline_and_paired_replay --no-cov -q` | **Passed** | 1 passed in 20.03 s; baseline exit 0, paired exit 100, five case IDs and 7/5 asserted |
| `make editorial-eval-install` | **Passed** | `npm ci` from the committed lock |
| `make editorial-eval-replay` | **Passed** | Baseline 6/6; paired 12 rows, 7 pass / 5 fail; raw Promptfoo 100 asserted; make exit 0 |
| `unshare -rn sh -c '... make editorial-eval-replay'` | **Passed** | Only `lo`; outbound probe `Errno 101`; baseline 6/6; paired 7/12; make exit 0 |
| Repeat offline replay + outcome comparison | **Passed** | identical `(description, success, reason)` for all 12 rows |
| `make lint` | **Passed** | black/isort/ruff/Makefile-tab/deprecation checks |
| `make type` | **Passed** | mypy pass; 3906 passed, 6 skipped; coverage ratchet 89.27% vs 88.44% |
| `make test` | **Passed** | 3906 passed, 6 skipped, 171 deselected |
| `make quality-gate` | **Passed** | 3 golden snapshots valid |
| `make docs-check` | **Passed** | 15 docs checked |
| `make quality` | **Failed — pre-existing** | Ruff/mypy legs passed; raw Bandit B404 + B607 at `scripts/editorial_critic_canary.py:42,269`. Reproduced with the same two findings in a detached `aeaa0a76` worktree. Not caused by this diff. |
| `make inventory-check` | **Failed — expected generated-baseline drift** | 10 changed lines across `make_targets`, `markdown_files`, `top_level_inventory.plans/`. Inventory is outside this phase's allowlist and is healed by the weekly autorefresh; not hand-edited. |
| `make test-contracts` / `make test-boundaries` / `make test-integration` / `make test-e2e` / `make verify-ci` / `make prepush` | **Not run** | Phase 3 has no contracts, workflow, storage, serving, integration or e2e changes. Phase 4 says not to rerun unrelated phase commands solely for a summary. |
| `make security` | **Not run** | `make quality` stopped at the pre-existing raw Bandit step before its pip-audit leg. The gated `scripts/security_gate.py` path was already recorded in Phase 2; no dependency or security surface changed here. |
| Remote hosted CI | **Not observed** | Local evidence only; no push/PR was performed. |

## Resolved versions and hashes

- Node `v24.19.0`; npm `11.17.0`; Promptfoo `0.124.1` (exact pin in
  `tools/editorial_eval/package.json` and lockfile).
- Python `3.13.12` repository `.venv`.
- Fixture SHA-256:
  - `cases.jsonl` — `ead7e52ea6f26d9a4ba2b75474d4c8576d623c2d8cc889768611b51bb2e59672`
  - `baseline.jsonl` — `a70c7e3e9ab929891e30ddd5f8d29c8dd4ecfd49f76c18f50fee0e7b7910a16b`
  - `candidate.jsonl` — `49069fae73a93786c84d242c84c16744cf8682a7cc7518a020254a28d831fb35`
- Baseline provenance: `quality_gate/golden/01_frog/snapshot.json` content,
  model `llama3.2:latest`, timestamp
  `2026-02-01T00:19:25.035684+00:00`; provider/prompt hash null (unknown).
  Candidate defects are synthetic and not human-reviewed.

## Verification-integrity checks

- No new `importorskip`. The one `pytest.mark.skipif` gates a real npm/Promptfoo
  integration test that ordinary `make test` must not depend on; the same file
  runs all contract and assertion semantics without npm.
- No `cast`, `# type: ignore`, blanket exception swallow or unconditional
  success return. `get_assert` passes only after the public validator and every
  literal expectation; unexpected exceptions propagate. `prepare.py` raises on
  every invalid input.
- Subprocess statuses are not swallowed: tests use argument arrays and assert
  explicit return codes. `make editorial-eval-replay` converts the expected
  negative-control exit 100 into a successful make run only after asserting the
  exact value, and prints that fact; raw `npm run eval:replay` still returns 100.
- Report negatives are real: the five failing case/label pairs are asserted in
  the test file and visible in `results.json`; the all-baseline control is
  separately required to pass first.

## Fresh-review find-list

No material Phase 3 gap is known to this executor. The reviewer should confirm:

1. E1–E5 against the fixtures/tests/results, including the exact five failures.
2. Accept or reject the two non-green repository gates above (pre-existing
   Bandit; generated inventory drift).
3. Confirm the development-only boundary: no CI/test wiring, no production
   model/prompt/schema/publication change, no secret or `.env` value included.
4. Confirm the synthetic/recorded provenance wording and the trailing-newline
   limitation are acceptable.

## Intentional limitations

- Checks are structural/literal, not factual, semantic or stylistic. The six
  cases are harness controls, not a production quality benchmark.
- Promptfoo 0.124.1 strips one trailing newline from string variables; fixtures
  avoid relying on it. A future real capture whose final newline matters must
  record that limitation.
- Importing the public validator initializes the test metrics singleton; the
  Promptfoo process may create a gitignored SQLite file under
  `tools/editorial_eval/data/metrics/test/`. No production metrics path is used.
- The tool is intentionally not in `make test`, `quality-gate`, `verify-ci` or
  hosted CI; adoption beyond the pilot needs separate evidence and review.
- No remote CI run is claimed.

## Rollback

Remove `tools/editorial_eval/`, `tests/data/editorial_eval/`,
`tests/unit/test_editorial_eval.py`, the two Make targets and
`docs/EDITORIAL_EVALUATION.md` (plus the one `docs/INDEX.md` row). No runtime,
database, publication, prompt, model or frontend change needs reversal. The
snapshot quality gate and Plan 048 enrichment evaluation are unaffected.
