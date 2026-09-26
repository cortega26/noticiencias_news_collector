# Plan 060 / Phase 7c-2 — Typed critic gate for the EditorAgent repair loops

> **Executor instructions**: Follow this spec step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition triggers, stop and report — do not improvise. When done,
> annotate the Phase 7 `EditorAgent` checkbox in `plans/060/todo.md` (partial:
> 7c-1 + 7c-2 done, remaining stages pending) and validate the plans ledger.
> This is a phase folder under plan 060 — no new ledger row.
>
> **Drift check (run first)**:
> `git diff --stat 48589d8..HEAD -- news_collector/components/editorial/ tests/unit/editorial/ tests/e2e_editorial_guardrails/`
> If any file changed since this spec was written, re-verify the "Current
> state" line references; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM (control-flow extraction inside `process_article`; no
  prompt, model, cache-filename or message changes allowed)
- **Depends on**: 7c-1 (typed `EditorialInput` + `EditorialStage` enum)
- **Category**: tech-debt / architecture (LAW-B3, LAW-B7, LAW-B9)
- **Planned at**: backend `48589d8`, 2026-09-26

## Why this phase exists

Plan 060 Phase 7's editor work:

> retain `EditorAgent.process_article(...) -> str` as a façade. Extract typed
> stages for normalized input, translated draft, adapted/critic-approved
> draft, enrichment result, and final publication artifact. Each stage
> declares input/output, cache identity, retry policy, provider/model
> provenance, and failure code.

7c-1 delivered the normalized input (`EditorialInput`) and the cache-identity
enum (`EditorialStage`). The adapted/critic-approved draft is next, and its
control flow is currently duplicated: the technical critic (Stage 3, ~75
lines) and the editorial critic (Stage 4, ~65 lines) each own their own
bounded evaluate → repair → re-evaluate loop with the same mechanics and
different policies. The retry policy and terminal failure semantics are
implicit in inline literals (`max_retries = 2`, `max_editorial_retries = 1`,
raise vs publish-with-caveat), so they cannot be inspected or tested without
running the whole façade.

This slice extracts the shared loop into a typed, pure module and declares
each gate's cache identity, bounded retry policy, and failure codes. Prompts,
repair prompts, cache paths, logging text and policy decisions stay in
`EditorAgent`.

## Current state (verified at `48589d8`)

- `ai_editor.py:2059` — `process_article` façade (input extraction via
  `EditorialInput.from_raw` since 7c-1).
- `ai_editor.py:2161-2235` — Stage 3 technical critic loop: `max_retries = 2`;
  per attempt `_editorial_output_repair_reason` then `_critic_pass` (legacy
  2-tuple `(is_valid, reason)` or current 3-tuple `(is_valid, reason,
  recoverable)` — both must keep working); checkpoint write `"ok"` on pass;
  repair base = publishable body else `translated_text`; irrecoverable →
  `ValueError("Article permanently discarded (irrecoverable): ...")`;
  exhausted → `ValueError("Translation Guardrail: Content rejected by critic
  after 2 retries. Reason: ...")`.
- `ai_editor.py:2237-2304` — Stage 4 editorial critic loop:
  `max_editorial_retries = 1`; `_critic_editorial_pass` (always 3-tuple);
  same checkpoint/repair mechanics; irrecoverable and exhausted both publish
  with a logged caveat instead of raising.
- `ai_editor.py:1776-1792` — `_editorial_output_repair_reason` and
  `_write_editorial_cache_if_valid` (repair-reason gate + stage-2 cache
  validity).
- `ai_editor.py:1794-1855` — `_repair_editorial(base, feedback, context)`.
- `ai_editor.py:387` — `_extract_publishable_body` (module-level) is the
  repair-base selector in both loops.
- `ai_editor.py:791` — `_extract_markdown_content` cleanup applied after
  every repair in both loops.
- Tests that must keep passing unchanged: `tests/unit/editorial/` +
  `tests/test_editor_agent.py` + `tests/test_ai_editor_tags.py` +
  `tests/test_terminology.py` + `tests/e2e_editorial_guardrails/`
  (baseline 2026-09-26: `tests/unit/editorial/ tests/test_editor_agent.py
  tests/test_ai_editor_tags.py tests/test_terminology.py` →
  **420 passed, 1 skipped**).
- Instance-method monkeypatching is load-bearing: tests replace
  `agent._critic_pass`, `agent._critic_editorial_pass`, `agent._repair_editorial`,
  `agent._translate_scientific`, `agent._adapt_editorial` and patch
  `agent._get_cache_path`. The gate must call these through the instance at
  call time (callables passed from `process_article`), and cache paths must
  still come from `self._get_cache_path(...)` in `process_article`.

## Scope

**In scope** (the only files to modify):

- NEW `news_collector/components/editorial/editorial_critic_gate.py` —
  `CriticVerdict`, `CriticFailureCode`, `CriticGatePolicy`,
  `TECHNICAL_CRITIC_GATE`, `EDITORIAL_CRITIC_GATE`, `CriticGateOutcome`,
  `run_critic_gate`.
- `news_collector/components/editorial/ai_editor.py` — replace the two inline
  loops with `run_critic_gate(...)` calls; keep every message, print, raise,
  caveat, checkpoint and cache update byte-identical.
- NEW `tests/unit/editorial/test_editorial_critic_gate.py`.
- `plans/060/todo.md` annotation only.

**Out of scope** (do NOT touch):

- Prompts, `_critic_pass` / `_critic_editorial_pass` internals, `_repair_editorial`
  internals, `_send_prompt`, provider retry behaviour.
- Provider/model provenance capture (later 7c slices).
- Stages 1/2/5/6/7 and the final artifact assembly.
- Any log string, `print()` text, stage ordering, error type, or returned
  Markdown.
- `docs/ARCHITECTURE.md` (no architecture claim changes yet).

## Design

### `editorial_critic_gate.py`

```python
@dataclass(frozen=True)
class CriticVerdict:
    is_valid: bool
    reason: str | None = None
    recoverable: bool = True


class CriticFailureCode(StrEnum):
    IRRECOVERABLE = "critic_irrecoverable"
    RETRIES_EXHAUSTED = "critic_retries_exhausted"


@dataclass(frozen=True)
class CriticGatePolicy:
    stage: EditorialStage   # cache identity of the gate checkpoint
    max_retries: int        # bounded repair attempts after the first verdict


TECHNICAL_CRITIC_GATE = CriticGatePolicy(EditorialStage.TECHNICAL_CRITIC_OK, 2)
EDITORIAL_CRITIC_GATE = CriticGatePolicy(EditorialStage.EDITORIAL_CRITIC_OK, 1)


@dataclass(frozen=True)
class CriticGateOutcome:
    content: str
    attempts: int
    passed: bool
    failure_code: CriticFailureCode | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class CriticGateHooks:
    evaluate: Callable[[str], CriticVerdict]
    is_repairable: Callable[[str], bool]
    repair: Callable[[str, str | None], str]
    cleanup: Callable[[str], str]
    on_pass: Callable[[], None]
    on_rejection: Callable[[int, str | None], None]
    on_repair: Callable[[str], None]


def run_critic_gate(
    policy: CriticGatePolicy,
    hooks: CriticGateHooks,
    *,
    content: str,
    fallback_content: str,
) -> CriticGateOutcome:
```

Loop, exactly mirroring both current blocks:

1. For `attempt in range(policy.max_retries + 1)`:
   - `verdict = evaluate(content)`.
   - valid → `on_pass()`, return `CriticGateOutcome(content, attempt + 1, True)`.
   - not recoverable → return `(content, attempt + 1, False, IRRECOVERABLE, verdict.reason)`
     (no repair, no `on_rejection`).
   - repairable attempt left → `on_rejection(attempt + 1, verdict.reason)`,
     `base = content if is_repairable(content) else fallback_content`,
     `content = cleanup(repair(base, verdict.reason))`, `on_repair(content)`.
   - last attempt → return `(content, attempt + 1, False, RETRIES_EXHAUSTED, verdict.reason)`.
2. The gate never logs and, on a valid policy, never raises: it returns
   terminal outcomes instead. A negative `max_retries` is rejected as a
   programming error (`ValueError`). The caller maps `failure_code` to
   raise/caveat with its historical messages.

Caller-specific closures in `process_article`, bundled into a
`CriticGateHooks(...)` per gate (Stage 3 shown; Stage 4 analogous with
`EDITORIAL_CRITIC_GATE`, `_critic_editorial_pass`,
`max_editorial_retries + 1`-equivalent formats and caveat logging):

- `evaluate` — Stage 3: repair-reason pre-check → `_critic_pass`, normalizing
  2-tuple/3-tuple to `CriticVerdict`; Stage 4: `_critic_editorial_pass`.
- `repair=lambda base, reason: self._repair_editorial(base, reason or "Unknown reason", editor_context)`
  (Stage 4 keeps its `"Calidad editorial insuficiente"` fallback).
- `is_repairable=lambda text: bool(_extract_publishable_body(text))`.
- `cleanup=self._extract_markdown_content`.
- `on_pass` — try checkpoint write with the historical warning text.
- `on_rejection` — the historical `print(...)` lines.
- `on_repair` — try `_write_editorial_cache_if_valid(cache_s2, content)` with
  the historical warning text.

## Test plan

- New `tests/unit/editorial/test_editorial_critic_gate.py` (pure gate, no
  EditorAgent):
  - pass on first verdict: `on_pass` called once, no repair, `attempts == 1`.
  - recoverable rejection then pass: `on_rejection(1, reason)` before repair,
    `repair` receives the fallback when the base is not repairable and the
    current content when it is, `cleanup` output is what the next verdict
    sees, `on_repair` gets the cleaned content, `attempts == 2`.
  - irrecoverable verdict: no `on_rejection`, no `repair`, `on_pass` not
    called, `failure_code == IRRECOVERABLE`, reason preserved.
  - exhausted (`max_retries=1`, always recoverable-invalid): repair called
    once, `on_pass` never called, `failure_code == RETRIES_EXHAUSTED`,
    returned content is the last repaired content.
  - `max_retries=0`: single verdict, no repair path, `on_pass`/`on_rejection`
    never called, `failure_reason` preserved.
  - rejection → repair → `on_repair` ordering pinned with a shared event log.
  - a `None` verdict reason is passed through to `repair` unchanged.
  - negative `max_retries` raises `ValueError` before any evaluation.
  - policy constants equal the historical retry budgets and stage identities.
- Existing editor suites remain green unchanged (420 baseline) — including
  `tests/e2e_editorial_guardrails/test_editor_agent_critic_recovery.py`,
  which exercises the real Stage 3 repair path through `process_article`.

## Steps

### Step 0: Baseline + drift

Run:
`python -m pytest tests/unit/editorial/ tests/test_editor_agent.py tests/test_ai_editor_tags.py tests/test_terminology.py -q`
and the drift check. STOP on non-green or drift.

### Step 1: Tests first

Write `test_editorial_critic_gate.py` (fails first: module does not exist).

### Step 2: Module + rewire

Add `editorial_critic_gate.py`, then replace the two loops in
`process_article`. Keep the surrounding cache read/checkpoint blocks, the
`ENABLE_EDITORIAL_CRITIC` / prompt-configured guard for Stage 4, all prints
and all raise/caveat messages byte-identical.

**Verify**: new tests + baseline suites green; `make lint`.

### Step 3: Gates + independent review

`make lint && make type && make test && make test-boundaries`;
`make quality-gate` (snapshot-first); `scripts/validate_plans_ledger.py`.
Run an independent fresh-context review of spec vs implementation (AGENTS
§0.1d) and resolve findings.

**Verify**: all exit 0; `git diff --stat` limited to in-scope files.

## Done criteria (machine-checkable)

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] `make quality-gate` snapshots valid
- [ ] `run_critic_gate` + `CriticGatePolicy` exist; `ai_editor.py` contains no
      inline critic retry loop literals (`max_retries = 2`,
      `max_editorial_retries = 1`)
- [ ] No existing editor test edited
- [ ] `git diff --name-only` lists only in-scope files
- [ ] `plans/060/todo.md` Phase 7 editor checkbox annotated (7c-1 + 7c-2);
      ledger OK

## STOP conditions

Stop and report if:

- Baseline/drift is not clean.
- Any attempt count, repair base, cleanup, checkpoint, cache-write, print or
  exception message changes.
- `_critic_pass` / `_critic_editorial_pass` / `_repair_editorial` signatures
  must change.
- An existing editor test must be modified.
- Any step's verification fails twice after a reasonable fix attempt.

## Git workflow

- Branch: `advisor/060-phase-7c2-critic-gate`.
- Commit: `refactor(editorial): extract the typed critic gate for stages 3-4`.
- Do NOT push or open a PR unless the operator instructed it.
