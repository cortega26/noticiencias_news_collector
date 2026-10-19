# Plan 080 — Phase 3 results (offline editorial replay pilot)

Recorded 2026-10-19. Checkout base `aeaa0a76`; branch
`advisor/080-editorial-eval`; implementation commit `c15ab1ec` (this evidence
file is committed separately). No production editor, prompt, model, schema,
publication or database code changed.

## Deliverable

| Path | Role |
| --- | --- |
| `tools/editorial_eval/package.json`, `package-lock.json` | Private development-only npm package; exact `promptfoo@0.124.1` pin. |
| `tools/editorial_eval/prepare.py` | Validated JSONL input contract and deterministic Promptfoo config/manifest writer. |
| `tools/editorial_eval/assertions.py` | `get_assert(output, context)` using the public Markdown validator plus literal expectations. |
| `tools/editorial_eval/README.md` | Usage, interpretation, offline procedure, limitations and rollback. |
| `tests/data/editorial_eval/*.jsonl` | Six-case corpus with one recorded baseline and synthetic candidate mutations. |
| `tests/unit/test_editorial_eval.py` | Validation, determinism, assertion semantics and opt-in real-Promptfoo integration. |
| `Makefile` | `editorial-eval-install` and `editorial-eval-replay`; not wired into `test`, `quality-gate`, `verify-ci` or CI. |
| `docs/EDITORIAL_EVALUATION.md`, one `docs/INDEX.md` row | Reviewer-facing usage and scope. |

No `.gitignore` change was needed: `reports/*` and `node_modules/` were already
ignored, and generated SQLite files match `*.db`.

## Fixture provenance

- Baseline outputs are the unchanged content of
  `quality_gate/golden/01_frog/snapshot.json` (recorded model
  `llama3.2:latest`, timestamp `2026-02-01T00:19:25.035684+00:00`). The source
  text is `quality_gate/golden/01_frog/input.txt`; the URL is the snapshot
  metadata's `https://example.com/frog-discovery`. `provider` and
  `prompt_hash` are null because the snapshot does not record them.
- Candidate outputs 2–6 are explicitly synthetic defects; the structural-pass
  candidate is a synthetic valid variant containing a fenced
  `{{ template_marker }}`. No synthetic fixture is labelled human-reviewed.
- Input hashes (SHA-256):
  - `cases.jsonl` — `ead7e52ea6f26d9a4ba2b75474d4c8576d623c2d8cc889768611b51bb2e59672`
  - `baseline.jsonl` — `a70c7e3e9ab929891e30ddd5f8d29c8dd4ecfd49f76c18f50fee0e7b7910a16b`
  - `candidate.jsonl` — `49069fae73a93786c84d242c84c16744cf8682a7cc7518a020254a28d831fb35`

## Acceptance evidence

### E1 — input contract fails clearly before replay

`tests/unit/test_editorial_eval.py` covers duplicate case IDs, empty corpus,
invalid JSON, wrong types, unknown fields, incomplete/extra case sets,
contradictory output/error records and null output without an error. Direct
`prepare.py` invocations return 0 on valid input and 2 with `error:` on stderr
for a missing file. Provider errors survive preparation (`provider_error` in the
manifest, nonempty `stored_error` in vars) and fail before content validation.
An empty string remains a captured output (`captured_output`, SHA-256 of `""`)
and reaches the content check. Observed: all contract tests pass.

### E2 — valid control and intended assertion failures

Baseline config: 6/6 passed, exit 0. Paired config: 12 rows, 7 passed / 5
failed, exit 100. The five failures are exactly:
| Row | Reason |
| --- | --- |
| `candidate:empty_body` | `editorial_placeholder_blocked`: body empty |
| `candidate:skipped_heading` | `editorial_heading_structure_invalid`: H1→H3 skip |
| `candidate:executable_markup` | `editorial_executable_content_blocked`: `<script>` |
| `candidate:prohibited_overclaim` | forbidden literal `garantiza la cura definitiva` |
| `candidate:missing_required_detail` | missing required literal `Centrolene mutum` |

`candidate:structural_pass` passes. Unit tests monkeypatch the public validator
to prove unexpected exceptions escape `get_assert` and that stored provider
errors short-circuit before content validation. The test file keeps the expected
five failing pairs separately from evaluator input.

Matched case set: 6/6 IDs in cases, baseline and candidate. Each
baseline/candidate pair is identical except for the intended mutation (the
structural-pass candidate additionally carries a valid H2 and a fenced
`{{ template_marker }}`). Harness outcome is 7/12 passing rows; this is a fixture
control result. No model was invoked, so this is not a model-versus-model
comparison and says nothing about generation quality. Provider-error count in
the seeded run: 0.

### E3 — repetition, alignment and provenance

Two offline replays with unchanged inputs produced identical
`(description, success, reason)` sets for all 12 rows (same five failures).
Rows are prepared and reported by case ID and label, not file row order.
`manifest.json` records per-row status, provenance, metadata, output hash, error
and the three input hashes; it contains no absolute paths. The baseline and
paired result files each contain all expected rows; there were zero
provider-level errors in the seeded run.

### E4 — offline, no generation, raw output preserved

Offline command (run 2026-10-19):

```bash
unshare -rn sh -c '
  cd /path/to/advisor-080-editorial-eval &&
  PROMPTFOO_PYTHON=$PWD/.venv/bin/python \
  PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1 \
  PROMPTFOO_DISABLE_REMOTE_GENERATION=true PROMPTFOO_DISABLE_SHARING=1 \
  PROMPTFOO_SELF_HOSTED=1 make editorial-eval-replay
'
```

Observed: `ip link` listed only `lo`; a `socket.create_connection(("1.1.1.1",
443))` probe failed with `OSError: [Errno 101] Network is unreachable`; the
baseline still passed 6/6 and the paired run returned the expected 7/12 with
Promptfoo exit 100. The Make target returned 0 after asserting the expected
100. The reasons above prove the Python assertion imported and ran under the
venv. `response.output == vars.logged_output` for all 12 rows, including the
fenced `{{ template_marker }}`, so echo replay preserved the captured strings
exactly (fixtures avoid a trailing newline; see limitations).

### E5 — reproducible commands and honest interpretation

`tools/editorial_eval/README.md` and `docs/EDITORIAL_EVALUATION.md` document the
prepare command, both npm scripts, their exits, the baseline-first order, the
offline procedure and the limits of the checks. A reviewer can rerun the same
commands; the unit test can be invoked separately with
`EDITORIAL_EVAL_PROMPTFOO_INTEGRATION=true`. No model is promoted and no
production gate is weakened.

## Commands and outcomes

| Command | Result |
| --- | --- |
| `.venv/bin/python -m pytest tests/unit/test_editorial_eval.py tests/unit/editorial/test_generated_article_guardrails.py --no-cov -q` | 37 passed, 1 skipped (opt-in integration) |
| `EDITORIAL_EVAL_PROMPTFOO_INTEGRATION=true .venv/bin/python -m pytest tests/unit/test_editorial_eval.py::test_real_promptfoo_baseline_and_paired_replay --no-cov -q` | 1 passed (20.03 s) |
| `make editorial-eval-install` | exit 0; `npm ci` from the committed lock |
| `make editorial-eval-replay` | exit 0; baseline 6/6, paired 7/12, raw Promptfoo exit 100 asserted |
| offline `unshare -rn ... make editorial-eval-replay` | exit 0; network denied; baseline 6/6, paired 7/12 |
| repeat offline replay + outcome comparison | identical 12-row outcomes |
| `make lint` | exit 0 |
| `make type` | exit 0 (mypy pass; 3906 passed, 6 skipped; coverage ratchet 89.27% vs baseline 88.44%) |
| `make test` | exit 0 (3906 passed, 6 skipped, 171 deselected) |
| `make quality-gate` | exit 0 (3 snapshots valid) |
| `make docs-check` | exit 0 (15 docs) |
| `make quality` | **exit 2, pre-existing**: raw Bandit B404 + B607 at `scripts/editorial_critic_canary.py:42,269`. Reproduced identically in a detached worktree at `aeaa0a76` with the same 2 findings. Ruff and mypy legs passed before that point. |
| `make inventory-check` | **exit 2, expected generated-baseline drift**: new markdown/Make targets/plan files vs committed `audit/00_inventory.json`. The inventory is outside this phase's allowlist and is healed by the weekly autorefresh workflow; not hand-edited. |

## Resolved versions

- Node `v24.19.0`; npm `11.17.0`; Promptfoo `0.124.1` (exact pin).
- Python `3.13.12`; repository `.venv` from `make bootstrap`.
- No live provider, model or network dependency was used.

## Pilot decision

**GO — retain the pilot.** E1–E5 are demonstrable with a recorded baseline, five
intended negative controls, a passing baseline control and an offline paired
replay. The package remains development-only and un-wired from ordinary gates.

## Limitations and reviewer notes

- The checks are structural/literal. They do not judge factual correctness,
  entailment, style or production quality; the six fixtures are controls.
- Promptfoo 0.124.1 removes exactly one trailing newline from string variables.
  Fixtures therefore carry no trailing newline; a real capture where the final
  newline matters needs that recorded. List vars require
  `disableVarExpansion: true`.
- Importing the public validator initializes the enrichment-metrics singleton in
  `RUN_ENVIRONMENT=test`; the Promptfoo process may create a gitignored SQLite
  file under `tools/editorial_eval/data/metrics/test/`. No production metrics
  path is used and no `EditorAgent` is constructed.
- `make quality`'s uncaught raw Bandit findings are pre-existing; `make quality`
  is not a clean gate on this base commit (same pattern recorded in Phase 2).
- `make inventory-check` drift is expected until the generated inventory is
  refreshed outside this phase's allowlist.
- Fresh review of Phase 3 is pending. This document does not mark the phase
  reviewed or Plan 080 complete.
