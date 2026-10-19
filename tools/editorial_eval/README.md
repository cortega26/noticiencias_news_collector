# Editorial replay evaluation (development-only)

Plan 080 Phase 3 pilot. This package replays **already captured** editorial
Markdown through deterministic checks. It does not generate articles, call a
model, publish anything, or change editorial policy.

## What it checks

For every captured output the evaluator applies:

1. The public `validate_generated_article_markdown` guardrail from
   `news_collector/components/editorial/ai_editor.py` (body presence, blocked
   placeholder/error prose, heading structure, minimum narrative length and
   executable HTML/MDX).
2. Case-specific **literal, case-sensitive** expectations from the case file:
   `required_substrings` must appear and `forbidden_substrings` must not.
3. A captured provider `error` is reported as a failed assertion before content
   validation. It is never reclassified as empty successful text.

These are narrow structural checks. They do **not** establish factual
correctness, semantic entailment, source fidelity, style quality or production
editorial performance. The six seeded cases are controls for the harness, not a
quality benchmark.

## Prerequisites

- Node 24 and npm 11 (the package pins `promptfoo` exactly; see
  `package.json` and `package-lock.json`).
- The repository Python environment (`.venv`, Python 3.13) from `make bootstrap`.
- Install the dev-only npm package once:

```bash
make editorial-eval-install   # cd tools/editorial_eval && npm ci
```

The package is private and development-only. It is not a dependency of the
public site or the admin app, and it is not wired into `make test`,
`quality-gate`, `verify-ci` or hosted CI.

## Input contract

All inputs are JSONL. Unknown fields are rejected so a typo cannot silently
weaken a check. An empty file is rejected.

`cases.jsonl`, one record per case:

| Field | Type | Rule |
| --- | --- | --- |
| `case_id` | string | nonempty, unique |
| `source_text` | string | nonempty |
| `language` | string | free-form language tag/name |
| `source_url` | string or null | optional source locator |
| `provenance` | `"synthetic"` or `"recorded"` | required |
| `review_evidence` | string or null | only for traceable human review |
| `required_substrings` | list of nonempty strings | literal expectations |
| `forbidden_substrings` | list of nonempty strings | literal prohibitions |

`baseline.jsonl` and `candidate.jsonl`, one record per case:

| Field | Type | Rule |
| --- | --- | --- |
| `case_id` | string | must match exactly one case |
| `output` | string or null | a string (including `""`) requires `error: null`; null requires a nonempty `error` |
| `error` | string or null | provider/capture failure |
| `provenance` | `"synthetic"` or `"recorded"` | required |
| `metadata` | object, optional | `model`, `provider`, `prompt_hash`, `source_hash`, `captured_at`; each string or null when present |

Both output files must cover the exact case set. Duplicates, missing outputs,
unknown cases, contradictory output/error pairs, and null output without an
error fail preparation before Promptfoo runs. Unknown metadata is represented as
null, never invented.

### Seeded controls

`tests/data/editorial_eval/` contains one recorded baseline output (copied
unchanged from `quality_gate/golden/01_frog/snapshot.json`, with its model,
timestamp and source hash preserved) and six case definitions. The candidate
outputs are explicit synthetic mutations:

| Case | Candidate defect | Expected check |
| --- | --- | --- |
| `structural_pass` | none; valid output with a literal `{{ template_marker }}` inside a code fence | passes |
| `empty_body` | empty string | public validator: empty body |
| `skipped_heading` | body starts at H3 | public validator: heading structure |
| `executable_markup` | `<script>` outside a fence | public validator: executable content |
| `prohibited_overclaim` | adds `garantiza la cura definitiva` | forbidden literal |
| `missing_required_detail` | removes `Centrolene mutum` | required literal |

The baseline control is 6/6 passing. The paired run is 12 rows: 7 passing and 5
failing. The five expected failures are the five candidate mutations above; the
test file asserts those exact case/label pairs separately from the evaluator.
None of these fixtures is human-reviewed, and they are not evidence of
production editorial quality.

## Prepare the configs

```bash
.venv/bin/python tools/editorial_eval/prepare.py \
  --cases tests/data/editorial_eval/cases.jsonl \
  --baseline tests/data/editorial_eval/baseline.jsonl \
  --candidate tests/data/editorial_eval/candidate.jsonl \
  --output-dir reports/editorial-eval
```

The command resolves input paths from the invocation directory and writes:

- `promptfooconfig.yaml` — paired baseline + candidate tests.
- `promptfooconfig.baseline.yaml` — baseline-only control.
- `manifest.json` — sorted case/row inventory, per-row status/provenance and
  SHA-256 hashes of inputs and outputs. It contains no absolute paths.

Configs and manifest are sorted by case ID and label. Raw output is stored under
`logged_output`; the assertion reference is relative to the generated config
directory. YAML is written with `safe_dump`; JSONL values are data, never shell
commands.

## Run

```bash
make editorial-eval-replay
```

The target prepares the inputs, validates the paired config, runs the all-passing
baseline control first, and only then runs the paired replay. It stops on any
preparation, validation or baseline failure. The paired run is expected to fail
five negative controls, so the Promptfoo process exits **100**; the target
asserts exactly that status and finishes successfully, printing the location of
`results.json`. A raw npm invocation preserves the 100:

```bash
cd tools/editorial_eval
npm run eval:validate   # 0
npm run eval:baseline   # 0, 6/6 pass
npm run eval:replay     # 100 by design, 7/12 pass
```

Set `PROMPTFOO_PYTHON` to the absolute `.venv/bin/python`. The Make target does
this automatically. `make editorial-eval-replay` does **not** install packages;
run `make editorial-eval-install` first.

The real integration test is opt-in because ordinary `make test` must not depend
on npm or Promptfoo:

```bash
EDITORIAL_EVAL_PROMPTFOO_INTEGRATION=true \
  .venv/bin/python -m pytest \
  tests/unit/test_editorial_eval.py::test_real_promptfoo_baseline_and_paired_replay \
  --no-cov -q
```

It asserts the baseline exit 0, the paired exit 100, the five failing case IDs,
the 7/5 outcome, and exact equality between each captured output and the echoed
`response.output`.

## Offline proof

Run the full replay with outbound networking denied:

```bash
unshare -rn sh -c '
  cd '"$PWD"' &&
  PROMPTFOO_PYTHON='"$PWD"'/.venv/bin/python \
  PROMPTFOO_DISABLE_TELEMETRY=1 \
  PROMPTFOO_DISABLE_UPDATE=1 \
  PROMPTFOO_DISABLE_REMOTE_GENERATION=true \
  PROMPTFOO_DISABLE_SHARING=1 \
  PROMPTFOO_SELF_HOSTED=1 \
  make editorial-eval-replay
'
```

`unshare -rn` leaves only loopback in the namespace. The only provider is
`echo`; assertions import the repository validator with
`NEWS_COLLECTOR_TEST_MODE=1` and `RUN_ENVIRONMENT=test`. No telemetry, sharing,
remote generation, package download or external request is required. The
passing/failing rows and reasons in `results.json` prove the assertion import
ran. `promptfoo` may still emit a local debug log under `~/.promptfoo/logs`;
that is filesystem-only and not a successful network request.

Importing the public validator initializes the repository's enrichment-metrics
singleton in test mode, so the Promptfoo process may create a gitignored SQLite
file under its working directory (`tools/editorial_eval/data/metrics/test/`).
Production metrics paths are not used.

## Interpret results

`results.json` follows Promptfoo 0.124.1's own schema. Read:

- `results.results[]` — one row per case/label, in prepared order.
- `testCase.description` — `baseline:<case_id>` or `candidate:<case_id>`.
- `success` — binary assertion outcome.
- `gradingResult.reason` — the typed assertion reason (content code, missing
  literal, forbidden literal, or captured provider error).
- `response.output` and `vars.logged_output` — the echoed output and the input.
- `failureReason` — `0` pass, `1` assertion failure; provider-level errors are
  distinct and remain visible.

Do not read a passing row as factual approval. Do not compare totals without
checking the specific case IDs. Provider errors belong in the denominator and
are reported as failures, not removed.

Known Promptfoo 0.124.1 behaviour: before rendering a prompt it removes exactly
one trailing newline from each string variable. The seeded fixtures therefore
store Markdown without a trailing newline; a captured output whose final newline
matters would need that limitation recorded. List variables are preserved with
`options.disableVarExpansion: true`, otherwise Promptfoo would treat
`required_substrings` as a cartesian list of values.

## Rollback and scope

Removing `tools/editorial_eval/`, `tests/data/editorial_eval/`,
`tests/unit/test_editorial_eval.py`, the two Make targets and the descriptive
docs fully removes the pilot. It has no runtime, schema, publication, prompt or
model dependency. It does not replace the snapshot quality gate or Plan 048's
enrichment evaluation. Add real captured cases only with traceable provenance
and explicit review evidence; do not label synthetic fixtures as reviewed.
