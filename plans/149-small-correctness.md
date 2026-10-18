# Plan 149: Four small correctness fixes (engine, cache, dashboard, Tkinter GUI)

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- news_collector/logic/workflows/refinery_engine.py news_collector/logic/workflows/audit_scheduler.py news_collector/logic/workflows/publication_pipeline.py news_collector/components/editorial/ai_editor.py news_collector/serving/dashboard_health.py news_collector/storage/database.py news_collector/storage/lifecycle_repository.py news_collector/logic/workflows/publication_reconciliation.py news_collector/validation/rules.py noticiencias/gui_config.py pyproject.toml Makefile tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M (four independent items; each can land on its own commit)
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug / tech-debt
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

Four independent defects, each small, each with a clean verification:

1. **A per-publish `ThreadPoolExecutor` is never shut down.** `RefineryEngine`
   builds one in `__init__` and passes it to the audit scheduler; nothing in
   production calls `shutdown()`. The serving process is long-lived (admin GUI +
   webhook receiver + publication dispatch), so each audited publish — and each
   batch item — leaves an idle worker thread blocked on its queue. The pipeline's
   own e2e harness already recorded the symptom ("leaked executor thread" causing
   180 s timeouts).
2. **A truncated/empty stage-1 translation cache is accepted as a valid draft.**
   `_load_translation_cache` returns the file text with no validation, while its
   two siblings validate their caches (enrichment regenerates on missing fields;
   stage 2 refuses to write an empty body). Because `Path.write_text` truncates
   before writing, a kill/ENOSPC mid-write leaves a 0-byte file, and the next run
   silently produces an article from the summary/metadata block instead of
   regenerating the translation.
3. **The dashboard's `validation` evidence attributes every rejection to
   "Content Guard".** `publication_events.event_type='rejected'` is emitted by at
   least three unrelated paths (the real Content Guard callback, pre-PR publish
   failures from `release_article_publishing`, and reconciler "legacy_projection"
   repairs), and the read model selects on the event type alone while printing
   "…intento(s) rechazado(s) por Content Guard".
4. **A live config GUI is excluded from coverage on a false rationale, and no
   test covers it.** `pyproject.toml`'s omit list calls
   `noticiencias/gui_config.py` "Legacy Streamlit config GUI (`make refinery`
   fallback): needs Streamlit" — but the module is **Tkinter**, imports no
   Streamlit, and is launched by `make config-gui`. It is the third writer of
   `config.toml` (the file holding tokens/keys) and has zero measured coverage.
   The doc claim is repeated in `docs/dev/TEST_SUITE_AUDIT.md:36`.

## Current state

- `news_collector/logic/workflows/refinery_engine.py:268-270` —
  `from concurrent.futures import ThreadPoolExecutor` / `self.executor = ThreadPoolExecutor(max_workers=1)`;
  `:991` passes `executor=self.executor` to the scheduler
  (`audit_scheduler.py:138,158` `executor.submit(...)`).
  `publication_pipeline.py:531-538` builds a fresh `RefineryEngine` per call, and
  `run_publication_batch` (`:817-856`) calls that once per item. A repo-wide grep
  finds no production `shutdown()` (only `system.shutdown()` for the collection
  path at `publication_pipeline.py:399`).
- `news_collector/components/editorial/ai_editor.py:2299-2315`
  (`_load_translation_cache`) vs `:2565-2590` (enrichment validates) and
  `:1942-1951` (`_write_editorial_cache_if_valid` refuses empty bodies).
- `news_collector/serving/dashboard_health.py:15-22` (rule statement),
  `:43` (`_VALIDATION_EVENT_TYPES`), `:177-187` (the rendered sentence);
  emitters: `storage/lifecycle_repository.py:843`,
  `logic/workflows/publication_callbacks.py:421` (real Content Guard),
  `storage/database.py:785-800` (`release_article_publishing`),
  `logic/workflows/publication_reconciliation.py:352-365`.
- `pyproject.toml:189-192` (the omit entry + rationale);
  `noticiencias/gui_config.py:1` ("Tkinter-based configuration editor"),
  `:5` `import tkinter as tk`; `Makefile:378-382` (`config-gui` target);
  `tools/config_editor.py:5` (compat launcher);
  `docs/dev/TEST_SUITE_AUDIT.md:36` (the repeated claim).

## Commands you will need

| Purpose          | Command                                                          | Provenance | Expected on success          |
|------------------|------------------------------------------------------------------|------------|------------------------------|
| Install/baseline | `make bootstrap`                                                 | declared   | exit 0                       |
| Lint             | `make lint`                                                      | declared   | exit 0                       |
| Types + coverage | `make type`                                                      | declared   | exit 0                       |
| Unit suite       | `make test`                                                      | declared   | all pass                     |
| Boundaries       | `make test-boundaries`                                           | declared   | exit 0                       |
| Focused tests    | `.venv/bin/pytest tests/unit/logic/workflows tests/unit/serving tests/unit/editorial -q --no-cov` | declared | all pass |
| Ledger           | `make plans-ledger-check`                                        | declared   | `validate_plans_ledger: OK`  |

Provenance: all `declared`.

## Scope

**In scope**:

- `news_collector/logic/workflows/refinery_engine.py` + `publication_pipeline.py`
  (item 1)
- `news_collector/components/editorial/ai_editor.py` (item 2 — the loader only)
- `news_collector/serving/dashboard_health.py` (item 3 — the predicate and the
  sentence; add a distinguishing marker at the read model, not at the emitters,
  unless you prove the emitters already record one)
- `noticiencias/gui_config.py` behaviour is **not** changed; decide and act on the
  coverage/doc claim (item 4)
- `pyproject.toml`, `docs/dev/TEST_SUITE_AUDIT.md` (item 4)
- `tests/` — focused tests per item

**Out of scope** (do NOT touch):

- The audit scheduler's threading model beyond receiving a shutting-down executor.
- Any other cache loader in `ai_editor.py`.
- The publication event emitters' semantics (only the read model changes).
- Deleting `gui_config.py` without an explicit operator decision (see Step 4).

## Git workflow

- Branch: `advisor/149-small-correctness`
- One commit per item; conventional commits, e.g.
  `fix(workflows): give the refinery engine an explicit executor lifecycle (plan 149)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make lint`, `make type`, `make test`,
`make test-boundaries`. Red baseline → STOP.

**Verify**: every command matches its expected result.

### Step 1: Give the engine an explicit lifecycle (item 1)

1. Add `close()` to `RefineryEngine`: `self.executor.shutdown(wait=False, cancel_futures=True)`
   with a docstring naming it the engine's only OS resource. Make it idempotent
   and safe to call when the audit never ran.
2. Call it from `run_publication_pipeline` in a `finally` around the work that
   owns the engine (so every return path, including early error returns, releases
   it). **Do not** shut down before the run's audit future result is consumed —
   read `_schedule_optional_audit` (`:989-1004`) and the scheduler's completion
   path first; if the future is consumed later, use `wait=False` and drain the
   future explicitly.
3. Do the same for the batch path if it constructs engines itself; otherwise the
   per-item `run_publication_pipeline` call already covers it.

**Verify**: a test asserting `threading.active_count()` returns to its baseline
after a run whose auditor triggers (use the existing test doubles for the
auditor; `audit_scheduler.py:74-76` documents the injection pattern).

### Step 2: Validate the stage-1 cache (item 2)

4. Make `_load_translation_cache` return `None` (⇒ regenerate) when the cached
   text is empty/whitespace-only after stripping, and for the same sanity
   conditions the siblings use (read them first; do not invent a length floor
   beyond what stage 2 already enforces). Update the docstring.
5. Keep the "hit" semantics for legitimate short translations (assert with a
   short-but-non-empty fixture).

**Verify**: a test that a 0-byte `*_translation.txt` triggers regeneration
(assert the loader returns `None` / the run re-requests the stage), plus a
non-empty cache still hits.

### Step 3: Stop misattributing rejections (item 3)

6. Determine, from the emitters, which signal distinguishes the Content Guard
   callback row from the release-path and reconciler rows. Candidates:
   `publication_events.details` carrying the callback payload
   (`publication_callbacks.py:421`) vs `reason`/`failure_class`
   (`database.py:785-800`) vs `source: "legacy_projection"`
   (`publication_reconciliation.py:352-365`). Prove it by reading each emitter.
7. Narrow `_validation_evidence`'s predicate to the Content Guard subset and
   change the rendered sentence to state only what the data proves (e.g.
   "N intento(s) rechazado(s) por el Content Guard" only for the narrowed set;
   otherwise "N intento(s) rechazado(s)" with the breakdown available in details).
8. If the emitter details genuinely cannot distinguish the paths, STOP: report
   that the fix needs an emitter-side marker (`details.source`) and propose it as
   a follow-up instead of guessing in the read model.

**Verify**: tests for each emitter shape: a callback-shaped rejection counts as
Content Guard; a release-path rejection does not; a legacy-projection repair does
not; the sentence reflects the narrowed count.

### Step 4: Resolve the Tkinter GUI question (item 4)

9. Correct the false rationale in `pyproject.toml`'s omit entry and
   `docs/dev/TEST_SUITE_AUDIT.md:36` (it is Tkinter, launched by `make config-gui`,
   not Streamlit/`make refinery`).
10. Then pick ONE and implement it:
    - **Option A (preferred if the module is to stay):** remove it from `omit`
    - and add a small coverage test for the pure parts of the save/load path
      (`_is_secret` handling, diff/validation helpers) using
      `tests/test_config_manager.py` as the pattern. If the Tkinter surface makes
      an import impossible in the test venv, import the module with a stubbed
      `tkinter` (monkeypatch `sys.modules`) and test the non-UI helpers — say so
      in the docstring.
      - **Option B (if the operator has said the Astro admin supersedes it):**
      - delete `noticiencias/gui_config.py`, the `config-gui` Make target, and
      `tools/config_editor.py`, and update `docs/` references. **Do not choose B
      without an explicit operator statement in the ledger row.**
11. If Option A cannot achieve meaningful coverage without a UI test framework,
    leave it omitted but with the corrected rationale + a one-line
    "accepted: UI shell, pure helpers covered by X" note; record the decision.

**Verify**: `make type` exits 0 (the omit list change is coverage-only);
`grep -n "Streamlit" pyproject.toml` no longer matches the gui_config entry;
`make inventory-refresh` if files changed.

## Test plan

- Item 1: thread-count regression test (Step 1) + a test that `close()` is
  idempotent and that an engine with no audit run closes cleanly.
- Item 2: 0-byte cache regenerates; non-empty cache hits.
- Item 3: three emitter shapes, one assertion each on the counted set.
- Item 4: as chosen (pure-helper coverage or removal).

**Verify**: `make test && make test-boundaries` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] No production code path constructs a `ThreadPoolExecutor` without a matching `close()`/`finally`
- [ ] The regression tests for items 1-3 fail on the pre-change code (prove each once)
- [ ] `pyproject.toml` no longer gives a false Streamlit rationale for `gui_config.py`,
      and item 4's decision is recorded with its evidence
- [ ] `make inventory-refresh` run if files were added/removed; `make inventory-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files (+ inventory baseline)
- [ ] `plans/README.md` row 149 updated; `make plans-ledger-check` → OK

## STOP conditions

- Shutting the executor down would cut off an in-flight audit whose result is
  consumed after the pipeline returns → report the actual ownership; do not
  introduce a global executor.
- The stage-1 fix would reject translations the pipeline legitimately caches
  (e.g. an intentionally empty case) → report before changing the contract.
- The rejection events cannot be distinguished without an emitter change → STOP
  after Step 6 and hand the follow-up back.
- `gui_config.py` cannot be imported at all in the test venv and Option B has no
  operator approval → do the rationale correction only and record the open
  decision.

## Maintenance notes

- `RefineryEngine.close()` becomes part of the engine's lifecycle contract; any
  future long-lived process holding an engine must call it.
- Reviewer should scrutinise: that the executor shutdown cannot deadlock a run
  (no `wait=True` before consuming the future) and that the dashboard sentence
  matches the narrowed predicate.
- **Deferred:** hoisting one engine/executor per *batch* (plan 133's Phase B
  territory). Unblocked by this plan landing.
