# Todo: Pre-Scorer and Critic Quality Fixes

Consult `spec.md` before every change.

## Phase 0 — Baseline and scope

- [x] Read `docs/AGENTS.md`
- [x] Inspect `pre_scorer.py`, `ai_editor.py`, related tests, and current logs
- [x] Reframe `spec.md` to this task
- [x] Confirm targeted baseline tests before code changes
  - `pytest tests/test_llm_rate_limiter.py tests/test_terminology.py tests/test_editor_agent.py`

## Phase 1 — PreScorer robustness

- [x] Add regression tests for mixed prose + JSON/list LLM outputs
- [x] Add regression test proving fallback is not FIFO
- [x] Implement local response parsing in `PreScorer`
- [x] Tighten the audience/relevance prompt for LatAm + broad-interest science
- [x] Add deterministic fallback ranking and fill-order logic
- [x] Re-run focused PreScorer tests and check them off
  - `pytest tests/e2e_editorial_guardrails/test_pre_scorer_quality.py`

## Phase 2 — Critic false-rejection hardening

- [x] Add regression test for empty stage-2 editorial output recovery
- [x] Add regression test for critic normalization of `No text provided`
- [x] Implement deterministic pre-critic content guard
- [x] Prevent empty/broken stage-2 output from being cached as good editorial content
- [x] Normalize critic `recoverable` when the failure reason is empty/missing text
- [x] Re-run focused EditorAgent tests and check them off
  - `pytest tests/e2e_editorial_guardrails/test_editor_agent_critic_recovery.py tests/test_ai_editor_tags.py tests/test_editor_agent.py tests/test_terminology.py`

## Phase 3 — Validation and review

- [x] Run `make lint`
  - Result: blocked by pre-existing repo-wide Black drift in unrelated files; our task did not attempt a global formatting sweep.
- [x] Run `make type`
  - Result: mypy passed; full pytest inside `make type` passed `862 passed, 3 skipped`; the target still exited non-zero because the repo-wide coverage ratchet baseline (`90.29%`) is currently above observed suite coverage (`86.96%`).
- [x] Run targeted pytest suite for the changed invariants
  - `pytest tests/test_llm_rate_limiter.py tests/test_terminology.py tests/test_editor_agent.py tests/e2e_editorial_guardrails/test_pre_scorer_quality.py tests/e2e_editorial_guardrails/test_editor_agent_critic_recovery.py`
- [x] Update this file with final status and any deviations
- [x] Ask a fresh sub-agent to review `spec.md` and the implementation for gaps
