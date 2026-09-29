# Plan 060 / Phase 7c-1 — Typed editorial input + stage cache identity

> **Executor instructions**: Follow this spec step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition triggers, stop and report — do not improvise. When done,
> annotate the Phase 7 `EditorAgent` checkbox in `plans/060/todo.md` (partial:
> 7c-1 done, LLM stages pending) and validate the plans ledger. This is a
> phase folder under plan 060 — no new ledger row.
>
> **Drift check (run first)**:
> `git diff --stat f354044..HEAD -- news_collector/components/editorial/ai_editor.py tests/unit/editorial/`
> If the file changed since this spec was written, re-verify the "Current
> state" line references; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (pure extraction on the input block + string→enum cache keys)
- **Depends on**: none; first slice of Phase 7c (`EditorAgent` typed stages)
- **Category**: tech-debt / architecture (LAW-B3, LAW-B9)
- **Planned at**: backend `f354044`, 2026-09-25

## Why this phase exists

Plan 060 Phase 7's editor work:

> retain `EditorAgent.process_article(...) -> str` as a façade. Extract typed
> stages for normalized input, translated draft, adapted/critic-approved
> draft, enrichment result, and final publication artifact. Each stage
> declares input/output, cache identity, retry policy, provider/model
> provenance, and failure code.

`process_article` is ~685 lines with six stages, four disk caches and two
retry loops. Extracting it in one change would be an unreviewable rewrite, so
7c is split; this slice delivers the two declarations every later stage
depends on:

1. **Normalized input** — `EditorialInput.from_raw(...)`: the exact field
   extraction and `article_id` derivation currently inlined at the top of
   `process_article`.
2. **Cache identity** — `EditorialStage`: a typed enum whose values are the
   historical cache-key strings, replacing bare literals at the five
   `_get_cache_path` call sites.

Nothing about prompts, LLM flow, caches, retries or output changes.

## Current state (verified at `f354044`)

- `ai_editor.py:2067-2116` — inline input extraction (dict + str branches,
  `article_id` derivation incl. sha256 of string input).
- `ai_editor.py:2052-2055` — `_get_cache_path(article_id, stage: str)` builds
  `{safe_id}_{stage}.txt`.
- Cache-key literals at `:2162` (`stage1_translation`), `:2172`
  (`stage2_editorial`), `:2197` (`stage2_5_critic_ok`), `:2270`
  (`stage2_6_editorial_critic_ok`), `:2359` (`stage4_enrichment`).
- Tests that must keep passing unchanged: `tests/unit/editorial/` +
  `tests/test_editor_agent.py` + `tests/test_ai_editor_tags.py` +
  `tests/test_terminology.py` (404 passed, 1 skipped baseline, 2026-09-25).
  Note `test_ai_editor_coverage.py:796-799` monkeypatches
  `_get_cache_path(self, article_id, stage)` and builds
  `f"{article_id}_{stage}.txt"`; a `StrEnum` formats as its value, so the fake
  keeps producing identical filenames.

## Scope

**In scope** (the only files to modify):

- NEW `news_collector/components/editorial/editorial_stages.py` —
  `EditorialStage(StrEnum)` with the five cache identities.
- NEW `news_collector/components/editorial/editorial_input.py` —
  `EditorialInput` frozen dataclass + `from_raw`.
- `news_collector/components/editorial/ai_editor.py` — use `EditorialInput`
  at the input block and `EditorialStage` at the five cache call sites.
  Signature and behavior of `_get_cache_path` unchanged (accepts `str`;
  `StrEnum` is a `str`).
- NEW `tests/unit/editorial/test_editorial_input.py`.
- `plans/060/todo.md` annotation only.

**Out of scope** (do NOT touch):

- LLM stages `_translate_scientific` / `_adapt_editorial` / critic passes /
  `_generate_enrichment_fields` / fact-check / assembly — 7c-2+.
- Category resolution, `clean_html`, min-length validation, `editor_context`
  construction, caches' read/write logic, retry loops.
- Any log string, `print()`, stage ordering, error type or returned Markdown.
- `docs/ARCHITECTURE.md` (no architecture claim changes yet — the debt section
  already scopes EditorAgent stages to Phase 7c).

## Design

### `editorial_stages.py`

```python
class EditorialStage(StrEnum):
    TRANSLATION = "stage1_translation"
    EDITORIAL = "stage2_editorial"
    TECHNICAL_CRITIC_OK = "stage2_5_critic_ok"
    EDITORIAL_CRITIC_OK = "stage2_6_editorial_critic_ok"
    ENRICHMENT = "stage4_enrichment"
```

Values are frozen legacy cache keys; changing one silently orphans caches.

### `editorial_input.py`

`EditorialInput` (frozen) fields: `article_id`, `title`, `summary`, `content`,
`content_mode`, `image_url`, `image_alt`, `source_id`, `source_name`,
`source_url`, `raw_category`, `metadata_category`.

`from_raw(raw_text: str | dict, explicit_article_id: str | None)` moves the
current extraction verbatim:

- `article_id = explicit_article_id or "unknown"`; dict branch then uses
  `str(raw_text.get("id") or "unknown")` when still `"unknown"`; str branch
  uses `sha256(content)[:8]` when still `"unknown"`.
- dict: `title/summary/content` with `or ""`, `content_mode` default
  `"full_text"`, `content` falls back to `summary`; `source_url` =
  `url` → `metadata.original_url` → `metadata.source_metadata.entry_id`;
  `raw_category` = `category`; `metadata_category` = `metadata.category`.
- str: `content = raw_text`, all other optional fields `None`,
  `content_mode = "full_text"`.

No cleaning, no category resolution (documented in the module docstring).

### `ai_editor.py` rewiring

Replace the inline block with the `from_raw` call + local unpacking so the rest
of the method is untouched; replace the five cache literals with
`EditorialStage.X`. Imports at module top (alphabetical/isort):

```python
from news_collector.components.editorial.editorial_input import EditorialInput
from news_collector.components.editorial.editorial_stages import EditorialStage
```

## Test plan

- New `tests/unit/editorial/test_editorial_input.py`:
  - dict extraction full fidelity incl. all three `source_url` fallbacks,
    `content`←`summary`, `content_mode` default/override, raw+metadata
    categories, None-safe `metadata`.
  - `article_id`: explicit wins over dict id; dict id when omitted; `"unknown"`
    when neither; explicit `"unknown"` falls through to dict id; string input
    hashes to `sha256[:8]`; explicit id with string input is preserved.
  - `EditorialStage` values equal the legacy cache strings, and
    `f"{article_id}_{EditorialStage.TRANSLATION}.txt"` formats as
    `{article_id}_stage1_translation.txt` (the monkeypatched-fake contract).
- Existing editor suites remain green unchanged (404 baseline).

## Steps

### Step 0: Baseline + drift

Run the baseline command and the drift check. STOP on non-green or drift.

### Step 1: Tests first

Write `test_editorial_input.py` (fails first).

### Step 2: Modules + rewire

Add the two modules, then rewire `ai_editor.py` (input block + five cache
sites). Do not touch anything else in the file.

**Verify**: new tests + baseline suites green; `make lint`.

### Step 3: Gates

`make lint && make type && make test && make test-boundaries`;
`make quality-gate` (snapshot-first); `scripts/validate_plans_ledger.py`.

**Verify**: all exit 0; `git diff --stat` limited to in-scope files.

## Done criteria (machine-checkable)

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] `make quality-gate` snapshots valid
- [ ] `EditorialInput.from_raw` + `EditorialStage` exist; `ai_editor.py`
      contains no bare `stage*` cache literals
- [ ] No existing editor test edited
- [ ] `git diff --name-only` lists only in-scope files
- [ ] `plans/060/todo.md` Phase 7 editor checkbox annotated; ledger OK

## STOP conditions

Stop and report if:

- Baseline/drift is not clean.
- Any extraction changes a field value, `article_id`, cache filename, or
  ordering.
- An existing editor test must be modified.
- Any step's verification fails twice after a reasonable fix attempt.

## Git workflow

- Branch: `advisor/060-phase-7c1-editorial-input-contract`.
- Commit: `refactor(editorial): type the editor input contract and stage cache identity`.
- Do NOT push or open a PR unless the operator instructed it.
