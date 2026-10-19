# Editorial replay evaluation (development-only)

Status: active pilot (plan 080 Phase 3). Development tooling only; no
production behavior changes.

The pilot lives in `tools/editorial_eval/` and replays **already captured**
editorial Markdown through deterministic checks. It reuses the public
`validate_generated_article_markdown` guardrail and adds narrow, literal case
expectations. It does not generate articles, call a model, publish, or change
prompts, schemas, models or editorial policy.

See `tools/editorial_eval/README.md` for the input contract, commands and
offline procedure. This page records the usage and interpretation rules that
matter to reviewers.

## What the result means

A passing replay row means:

- the captured output passed the public generated-Markdown guardrails, and
- every required literal appeared, and
- no forbidden literal appeared.

It does **not** mean the article is factually correct, entailed by its source,
well written, or representative of production quality. The seeded controls are
harness tests, not an editorial benchmark. Six cases are deliberately small:
one valid control, four public-validator defects and one missing source detail.
The paired run is expected to produce 12 rows, 7 passing and 5 failing; the
all-baseline control must be 6/6 passing.

Captured provider errors are failures in the denominator and are never treated
as empty successful text. Reports must keep harness success, content-check
success and production performance distinct.

## Commands

```bash
make editorial-eval-install
make editorial-eval-replay
EDITORIAL_EVAL_PROMPTFOO_INTEGRATION=true .venv/bin/python -m pytest tests/unit/test_editorial_eval.py::test_real_promptfoo_baseline_and_paired_replay --no-cov -q
```

`make editorial-eval-replay` prepares the seeded inputs, validates the paired
config, runs the all-passing baseline control first, and stops if preparation,
validation or the baseline fails. Only then does it run the paired replay. The
paired replay intentionally returns Promptfoo exit 100 because five negative
controls must fail; the target asserts that exact exit and completes
successfully. The raw npm script `npm run eval:replay` preserves the 100.

The package is a private, development-only npm dependency pinned to an exact
Promptfoo version. It is not a dependency of the site or admin app and is not
wired into `make test`, `quality-gate`, `verify-ci` or hosted CI.

## Offline and provenance rules

- Run the acceptance replay with outbound networking denied (`unshare -rn` in
  this repository's Linux development environment) and the documented
  `PROMPTFOO_DISABLE_*` settings. The only provider is `echo`.
- Assertions import project code only after setting
  `NEWS_COLLECTOR_TEST_MODE=1` and `RUN_ENVIRONMENT=test`. No `EditorAgent`,
  provider discovery, publication or production database path is used.
- Preparation sorts cases and rows by case ID and label, writes YAML with
  `safe_dump`, and records content SHA-256 hashes in the manifest instead of
  machine-specific paths.
- Raw captured Markdown is passed as data. Promptfoo 0.124.1 removes exactly
  one trailing newline from string variables; fixtures avoid relying on one.
- Do not add live provider wrappers, LLM judges, embeddings or external URLs to
  this pilot.

## Rollback

Delete the tool package, its fixtures and unit test, the two Make targets and
this page. Nothing in collection, publication, serving, storage or the public
frontend depends on them. The snapshot quality gate and Plan 048's enrichment
evaluation are unaffected.

## Related documents

- `docs/editorial_quality_system.md` — production editorial policies and gates.
- `docs/EDITORIAL_EVALUATION_PROTOCOL.md` — human-led evaluation protocol.
- `tests/README.md` — test suite map and evidence conventions.
