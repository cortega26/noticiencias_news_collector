# Plan 060 / Phase 7c-3 — Typed cache-backed stages (translated draft + enrichment result)

> **Executor instructions**: Follow this spec step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition triggers, stop and report — do not improvise. When done,
> annotate the Phase 7 `EditorAgent` checkbox in `plans/060/todo.md` (partial:
> 7c-1 + 7c-2 + 7c-3 done, final artifact + provenance pending) and validate
> the plans ledger. This is a phase folder under plan 060 — no new ledger row.
>
> **Drift check (run first)**:
> `git diff --stat a59ca1c..HEAD -- news_collector/components/editorial/ tests/unit/editorial/ tests/e2e_editorial_guardrails/`
> If any file changed since this spec was written, re-verify the "Current
> state" line references; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (cache read/generate/persist extraction on two stages; no
  prompt, cache filename, message or ordering changes allowed)
- **Depends on**: 7c-1 (`EditorialStage`) and 7c-2 (`run_critic_gate` pattern)
- **Category**: tech-debt / architecture (LAW-B3, LAW-B7, LAW-B9)
- **Planned at**: backend `a59ca1c`, 2026-09-26

## Why this phase exists

Plan 060 Phase 7's editor work:

> retain `EditorAgent.process_article(...) -> str` as a façade. Extract typed
> stages for normalized input (7c-1), translated draft, adapted/critic-approved
> draft (7c-2), enrichment result, and final publication artifact. Each stage
> declares input/output, cache identity, retry policy, provider/model
> provenance, and failure code.

Two cache-backed stages still inline their cache mechanics in the façade:

1. **Stage 1 translated draft** — `cache exists → read; else translate → write`.
2. **Stage 6 enrichment result** — a parse/validate/regenerate block plus a
   *duplicated* `generate + persist` body (cache-hit-unusable and cache-miss
   branches both repeat it).

The shared shape — "load a usable cached artifact, else generate and persist
it" — is one bounded decision used at two concrete call sites (LAW-B9), and
both stages need the same typed outcome so `process_article` can stop juggling
raw `str`/`dict` values. This slice extracts that runner, types the artifacts,
and migrates both stages. Parsing, validation warnings, cache I/O, prompts and
generation stay in `EditorAgent` closures.

## Current state (verified at `a59ca1c`)

- `ai_editor.py:2139-2147` — Stage 1 block: header print; `cache_s1 =
  _get_cache_path(article_id, TRANSLATION)`; hit → print `(Loaded from
  cache: ...)` + `read_text`; miss → `_translate_scientific(input_text)` +
  `write_text` (no try/except; write errors propagate).
- `ai_editor.py:2362-2420` — Stage 6 block: header print; `cache_s4 =
  _get_cache_path(article_id, ENRICHMENT)`; local `_enrichment_cache_is_usable`
  (needs every `_V2_REQUIRED_ENRICHMENT_FIELDS` key truthy); hit → print +
  `json.loads` with `logger.warning("Invalid enrichment cache, regenerating:
  {e}")` on parse failure, `logger.warning("Incomplete enrichment cache
  ignored (missing required V2 fields); regenerating.")` when non-None but
  unusable; usable → use `cached_enrichment`; otherwise (and on miss) →
  `_generate_enrichment_fields(final_content, title, source_url=...,
  source_name=...)` + `cache_s4.write_text(json.dumps(fields,
  ensure_ascii=False))` guarded by `logger.warning("Failed to persist
  enrichment cache: {_e}")`. The generate+persist body is duplicated verbatim.
- `ai_editor.py:391` — `_V2_REQUIRED_ENRICHMENT_FIELDS` (module constant, also
  used by the V2 frontmatter gate downstream — do not move/rename).
- `ai_editor.py:2073` — `process_article` façade (7c-1 input, 7c-2 critic gates).
- Instance-method monkeypatching is load-bearing: tests replace
  `agent._translate_scientific`, `agent._generate_enrichment_fields` and patch
  `agent._get_cache_path`; closures must call these through the instance at
  call time and paths must still come from `self._get_cache_path(...)`.
- Tests that must keep passing unchanged: `tests/unit/editorial/` +
  `tests/test_editor_agent.py` + `tests/test_ai_editor_tags.py` +
  `tests/test_terminology.py` (baseline 2026-09-26: **429 passed, 1
  skipped**), plus `tests/e2e_editorial_guardrails/`.

## Scope

**In scope** (the only files to modify):

- NEW `news_collector/components/editorial/editorial_cached_stage.py` —
  `CachedStageOutcome[T]`, `CachedStageHooks[T]`, `run_cached_stage`.
- `news_collector/components/editorial/ai_editor.py` — Stage 1 and Stage 6
  delegate to the runner; extract their load/persist closures with identical
  prints, warnings and cache calls.
- NEW `tests/unit/editorial/test_editorial_cached_stage.py`.
- `plans/060/todo.md` annotation only.

**Out of scope** (do NOT touch):

- Prompts, `_translate_scientific` / `_generate_enrichment_fields` internals,
  `_send_prompt`, provider retry behaviour.
- `_V2_REQUIRED_ENRICHMENT_FIELDS` (stays in `ai_editor.py`).
- Stage 2/3/4 (7c-2), Stage 5, Stage 7 and the final artifact assembly.
- Provider/model provenance capture (later 7c slice).
- Any log string, `print()` text, stage ordering, error type or returned
  Markdown.
- `docs/ARCHITECTURE.md` (no architecture claim changes yet).

## Design

### `editorial_cached_stage.py`

```python
T = TypeVar("T")


@dataclass(frozen=True)
class CachedStageOutcome(Generic[T]):
    """One stage artifact and how it was produced."""

    stage: EditorialStage
    value: T
    from_cache: bool


@dataclass(frozen=True)
class CachedStageHooks(Generic[T]):
    """Callbacks one cache-backed stage needs; supplied by `EditorAgent`."""

    load_cached: Callable[[], T | None]
    generate: Callable[[], T]
    persist: Callable[[T], None]


def run_cached_stage(
    stage: EditorialStage,
    hooks: CachedStageHooks[T],
    *,
    cache_present: bool,
) -> CachedStageOutcome[T]:
    if cache_present:
        cached = hooks.load_cached()
        if cached is not None:
            return CachedStageOutcome(stage, cached, True)

    value = hooks.generate()
    hooks.persist(value)
    return CachedStageOutcome(stage, value, False)
```

Contract notes:

- `load_cached` returns `None` when the cache exists but is unusable (parse
  error, incomplete payload) — its closure owns the warning text, exactly as
  the inline block did. JSON `null` is returned as `None` and regenerates
  **without** the "incomplete" warning (historical behavior preserved).
- `persist` owns its own error handling (Stage 6 swallows with a warning,
  Stage 1 lets write errors propagate) — the runner does not wrap it.
- The runner is pure (no I/O, no logging); the closures carry all side effects.

### Callers

- Stage 1: `_load_translation_cache` prints `(Loaded from cache: ...)` and
  reads; `generate=lambda: self._translate_scientific(input_text)`;
  `persist=lambda text: cache_s1.write_text(text, encoding="utf-8")`.
- Stage 6: `_enrichment_cache_is_usable` / `_load_enrichment_cache` /
  `_persist_enrichment_cache` keep the current warnings verbatim;
  `generate=lambda: self._generate_enrichment_fields(final_content, title,
  source_url=source_url or "", source_name=source_name or "")`.
- `cache_present=cache_sN.exists()` still computed in `process_article` from
  `self._get_cache_path(...)` (monkeypatch contract preserved).

## Test plan

- New `tests/unit/editorial/test_editorial_cached_stage.py` (pure runner):
  - cache hit with a usable value → returns it, `from_cache is True`,
    `generate`/`persist` never called, `load_cached` called once.
  - cache present but `load_cached` returns `None` → regenerates, persists the
    generated value, `from_cache is False`.
  - cache absent → `load_cached` never called; generate → persist → return.
  - generated value passes through unchanged (identity for a dict payload).
  - declared stage identity is preserved in the outcome for both stages.
  - a `generate` exception propagates and `persist` is never called.
- Existing editor suites remain green unchanged (429 baseline) — the e2e
  guardrail and enrichment-field suites exercise both rewired stages.

## Steps

### Step 0: Baseline + drift

Run:
`python -m pytest tests/unit/editorial/ tests/test_editor_agent.py tests/test_ai_editor_tags.py tests/test_terminology.py -q`
and the drift check. STOP on non-green or drift.

### Step 1: Tests first

Write `test_editorial_cached_stage.py` (fails first: module does not exist).

### Step 2: Module + rewire

Add `editorial_cached_stage.py`, then make Stage 1 and Stage 6 delegate.
Keep both blocks' prints, warnings, cache filenames and ordering identical.

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
- [ ] `run_cached_stage` + `CachedStageHooks`/`CachedStageOutcome` exist;
      Stage 1 and Stage 6 have single generate+persist paths
- [ ] No existing editor test edited
- [ ] `git diff --name-only` lists only in-scope files
- [ ] `plans/060/todo.md` Phase 7 editor checkbox annotated (7c-1/7c-2/7c-3);
      ledger OK

## STOP conditions

Stop and report if:

- Baseline/drift is not clean.
- Any cache filename, print/warning/exception text, attempt/with/without-cache
  ordering, or generated value changes.
- An existing editor test must be modified.
- Any step's verification fails twice after a reasonable fix attempt.

## Git workflow

- Branch: `advisor/060-phase-7c3-cached-stages`.
- Commit: `refactor(editorial): type the cache-backed translation and enrichment stages`.
- Do NOT push or open a PR unless the operator instructed it.
