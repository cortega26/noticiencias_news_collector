# Phase 3 — Offline editorial replay pilot

Prerequisite: Phase 0. Risk: Critical (development dependency); no production
behavior change. This phase evaluates already-captured output and tests the
evaluation harness. It does not claim to evaluate live generation performance.

## Read first and copy patterns

Read `scripts/quality_gate.py`, the three `quality_gate/golden/` directories,
`validate_generated_article_markdown` and `GeneratedArticleValidationError` in
`news_collector/components/editorial/ai_editor.py`, and
`tests/unit/editorial/test_generated_article_guardrails.py`. Read the official
Promptfoo echo, Python assertions and CLI documentation from Phase 0.

Reuse the **public** `validate_generated_article_markdown(markdown)` function
without instantiating `EditorAgent`. It checks body/heading/executable-content
guardrails, not all frontmatter rules or factual correctness. Do not copy its
regexes or thresholds into an evaluation-specific validator. Re-read before
implementation because this module had unrelated active edits during planning.

## File scope

- **New:** `tools/editorial_eval/package.json`, `package-lock.json`,
  `prepare.py`, `assertions.py`, `README.md`.
- **New:** `tests/data/editorial_eval/` with case manifest and small recorded or
  explicitly synthetic baseline/candidate fixtures.
- **New:** `tests/unit/test_editorial_eval.py`.
- **New:** `docs/EDITORIAL_EVALUATION.md` describing usage and interpretation.
- `Makefile` for optional `editorial-eval-install` and `editorial-eval-replay`
  entry points, `.gitignore` for generated local reports if not already covered.
- Plan checklist/evidence. No production editor/prompt/model/schema changes.

Use a private development-only npm package with an exact tested Promptfoo pin
and Node 24. Keep it out of the public site's and admin's runtime dependencies.
Do not add it to ordinary `make test`, `quality-gate`, `verify-ci`, or hosted CI
yet. The pilot must demonstrate usefulness before expanding installation cost.

## Work package A — Inputs and honest provenance

Create a typed, validated local input contract (test/tool-only types may remain
inside these tools; they are not new runtime cross-package contracts):

1. `cases.jsonl`: one record per `case_id` (nonempty string), `source_text`
   (nonempty string), `language` (string), `source_url` (string or null),
   `provenance` (`synthetic` or `recorded`), `review_evidence` (string or null),
   `required_substrings` and `forbidden_substrings` (lists of nonempty strings).
   Expectations may include required literal excerpts or forbidden known-error phrases. State
   clearly that these are narrow checks, not semantic entailment judgments.
2. `baseline.jsonl` and `candidate.jsonl`: `case_id`, `output` (raw Markdown or null),
   `error` (nullable), provenance, and optional actual model/provider, prompt
   hash, source hash and capture timestamp. Model metadata may be unknown but
   must not be fabricated. Require either a string output (including empty text,
   which must reach and fail the content check) with null error, or null output
   with a nonempty error string. Keep optional capture metadata in a named
   `metadata` object with explicit optional string fields `model`, `provider`,
   `prompt_hash`, `source_hash`, and `captured_at`.
3. Validate unique IDs, complete matching case sets and input
   types before constructing a run. Missing outputs must fail preparation;
   provider failures must remain visible as failures, never disappear from the
   denominator or get reclassified as empty successful text.

Seed six small cases: structural pass, empty/placeholder body, skipped heading
level, executable markup, a known prohibited overclaim, and a fixture with a
required source-specific literal detail missing. For rejection controls, use
explicitly synthetic mutations and record their expected outcomes. Ensure each
case exercises its intended check (e.g. executable-markup fixture otherwise
passes body length/heading requirements). Do not call synthetic fixtures human
reviewed. All six **baseline** outputs should pass their checks; the candidate
structural-pass case remains valid and the other five contain the corresponding
defect. Expected paired outcome: 12 rows, 7 passing and 5 failing. Assert the
specific five case/label pairs, not only the totals. Store the expected control
outcomes separately in test assertions; never feed them into the evaluator as
the answer. Do not imply these cases establish production editorial quality.

Existing golden snapshots may supply replay inputs with their original metadata,
but do not overwrite them, invent `_meta.generated_by`, or execute
`quality_gate_refresh.py`. Do not import Plan 048 topic/entity gold as article
quality labels. Add reviewed real examples later only with traceable review.

## Work package B — Deterministic assertions and prepared config

Implement `assertions.py:get_assert(output, context)` using the documented
Python assertion signature. Read case expectations/error status from
`context["vars"]`. Return a typed `{pass, score, reason}` result with binary score
and a useful reason. Catch only expected content-validation failures as failed
assertions; unexpected errors must remain evaluator errors. Do not silently
repair input/output before evaluation.

Apply the public generated-Markdown validator, then case-specific checks using
literal, case-sensitive containment in the unchanged output string. This is
deliberately narrow; do not add regex, stemming or inferred number equivalence.
Treat stored provider errors as failures before content validation. Use neither
LLM judges nor embeddings nor external URLs. Import project code only after
enabling the repository's test-mode isolation; no `EditorAgent` instance, cache,
provider discovery, publication or DB writes are needed.

Implement this **new** preparation CLI:

```bash
.venv/bin/python tools/editorial_eval/prepare.py --cases tests/data/editorial_eval/cases.jsonl --baseline tests/data/editorial_eval/baseline.jsonl --candidate tests/data/editorial_eval/candidate.jsonl --output-dir reports/editorial-eval
```

It writes deterministic `promptfooconfig.yaml`, `promptfooconfig.baseline.yaml`
and `manifest.json`, sorted by case ID and label. The first config contains both
labels; the baseline config contains only the six baseline rows. Each output
becomes a named test with raw output
in `logged_output`, source/case data, and preserved provenance in variables.
Resolve input CLI paths from the invocation's working directory, as normal for
CLI tools; read source/output text directly from JSONL, not additional paths.
Emit assertion paths appropriate to the generated config's directory and record
content hashes rather than machine-specific paths as provenance. Use safe YAML
serialization and subprocess argument arrays; output strings are data, never
shell commands or unescaped YAML templates.

Copy this documented shape, replacing the file path with the resolved assertion
location. Do not use the trivial example `bool(output.strip())` as the evaluator:

```yaml
prompts:
  - '{{logged_output}}'
providers:
  - echo
defaultTest:
  assert:
    - type: python
      value: file://PATH_TO_ASSERTIONS.py:get_assert
tests: [] # populated by preparation, never accepted empty
```

No custom provider is needed for replay. Do not add a live Ollama/NVIDIA/Gemini
wrapper or allow configuration to select arbitrary provider IDs in this pilot.
Raw Markdown may contain template syntax; prove replay receives it unchanged.

## Work package C — Run and interpret

Add these npm scripts in the isolated tooling package. Paths are relative to
`tools/editorial_eval`, where npm runs package scripts:

```json
{
  "eval:validate": "promptfoo validate -c ../../reports/editorial-eval/promptfooconfig.yaml",
  "eval:replay": "promptfoo eval -c ../../reports/editorial-eval/promptfooconfig.yaml --max-concurrency 1 --no-cache --no-share -o ../../reports/editorial-eval/results.json",
  "eval:baseline": "promptfoo eval -c ../../reports/editorial-eval/promptfooconfig.baseline.yaml --max-concurrency 1 --no-cache --no-share -o ../../reports/editorial-eval/baseline-results.json"
}
```

Expose `make editorial-eval-install` as `npm ci` in that package, and a separate
`make editorial-eval-replay` that prepares the seeded inputs, validates config,
runs the all-passing `eval:baseline` control first, then the paired `eval:replay`.
Fail immediately if preparation, validation or baseline fails. The final paired
run returns the expected negative-control status. Neither replay nor validation
may install packages implicitly. Integration tests can invoke the two npm
scripts separately to assert both results.

Set `PROMPTFOO_PYTHON` to the absolute repository `.venv/bin/python`. Disable
telemetry/version checks with `PROMPTFOO_DISABLE_TELEMETRY=1` and
`PROMPTFOO_DISABLE_UPDATE=1`; also set `PROMPTFOO_DISABLE_REMOTE_GENERATION=true`,
`PROMPTFOO_DISABLE_SHARING=1`, and `PROMPTFOO_SELF_HOSTED=1`. Recheck support in the
pinned version. [Telemetry settings](https://www.promptfoo.dev/docs/configuration/telemetry/),
[offline FAQ](https://www.promptfoo.dev/docs/faq/). Use `--no-cache` and
`--no-share`, concurrency 1, with output under `reports/editorial-eval/`.
Verify installed execution under blocked network access; echo alone is not proof
that telemetry or assertion imports never attempt external connections. The
FAQ permits an opt-out acknowledgment, so flags alone do not guarantee zero
outbound attempts. Acceptance requires successful replay with outbound traffic
denied, no provider invocation, and no successful external requests.

The documented base command is:

```text
promptfoo eval -c <prepared-config> --max-concurrency 1 --no-cache --no-share -o <results.json>
```

Preserve its nonzero exit status: default evaluation failure is 100 and other
errors 1. Do not change failure thresholds to hide negative controls. The seeded
negative-control run is **expected to return 100**; its integration test asserts
that exit and the specific failing case IDs. A separate all-passing control
must return zero. Report the two results separately.

Use Promptfoo's actual pinned output schema/report, verified against a sample,
to inspect paired baseline/candidate outcomes. Do not invent result JSON fields.
In `tests/phase-3-results.md`, record: total/matched cases, failed case IDs and
reasons, provider-error count, missing-input rejections, changes between paired
outputs, tool version and input hashes. Distinguish harness success from content
success and fixture controls from actual model comparisons.

## Acceptance and verification

- **E1:** required IDs match; duplicates, missing outputs, empty corpus, invalid
  JSON/types and contradictory output/error records fail clearly before replay.
- **E2:** known valid control passes; each seeded defect fails the intended
  assertion. Real validator exceptions retain their meaning; evaluator bugs
  cannot be mistaken for content failures.
- **E3:** repeated replay yields identical case outcomes with unchanged input;
  comparisons align by case ID, not row order. Reports include every case,
  including explicit provider errors; provenance survives preparation.
- **E4:** no network, generation, production file writes, editor construction or
  implicit package downloads; raw captured output is preserved exactly.
- **E5:** a reviewer can reproduce a baseline/candidate difference using the
  documented commands. Documentation accurately limits the conclusions to the
  checks performed. No model is promoted and no production gate is weakened.

```bash
.venv/bin/python -m pytest tests/unit/test_editorial_eval.py tests/unit/editorial/test_generated_article_guardrails.py --no-cov -q
make editorial-eval-install
make editorial-eval-replay
make lint
make type
make test
make quality-gate
make quality
make docs-check
```

The replay negative-control exit is expected and must be asserted/documented,
not appended to an `&&` chain that prevents the remaining checks. Run the
all-passing and negative-control integrations under offline conditions after
dependency provisioning. Add integration invocation instructions to the tool's
README; default Python tests may mock subprocess transport but not claim the
real Promptfoo integration ran.

**Pilot go/no-go:** retain the tool only after E1–E5 demonstrate reproducible
comparison beyond calling the existing validator on one file. If the pinned
tool cannot run offline, its output cannot be interpreted reliably, or the
maintenance cost outweighs paired replay, record NO-GO and remove its package
and unused tooling before delivery. Keep useful independent regression cases.
Do not implement a homegrown evaluation platform as a fallback. A no-go is an
explicit partial program outcome, not successful Promptfoo adoption.
