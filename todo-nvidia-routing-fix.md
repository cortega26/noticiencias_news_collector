# Todo: Fix NVIDIA Provider Routing

Tracks the implementation described in `spec-nvidia-routing-fix.md`.
Run `make lint && make test` after each phase.

> **Retroactively reconciled 2026-08-02**: this checklist was never updated after
> the work landed in commit `fe21829` (2026-04-28). Verified now against current
> code: `tests/test_nvidia_routing_fix.py` exists with 20 tests, all passing
> (`.venv/bin/python -m pytest tests/test_nvidia_routing_fix.py -q` → 20 passed),
> and `admin_panel.py`/`ai_editor.py` carry the diffs described below. The two
> manual-verification items (Codacy runs, Streamlit walkthrough) were not
> re-run/re-verified as part of this reconciliation — left unchecked honestly
> rather than assumed.

---

## Phase 0 — Baseline

- [x] Read spec-nvidia-routing-fix.md fully
- [x] Confirm existing test suite passes as-is
- [x] Create `tests/test_nvidia_routing_fix.py` with failing tests (spec §6)

---

## Phase 1 — Tests (failing first)

- [x] **1.1** `test_config_summary_shows_nvidia_model_when_nvidia_active` — G1
- [x] **1.2** `test_ollama_sections_hidden_when_nvidia_active` — G2 (spec named it `_collapsed_`; shipped as `_hidden_`)
- [x] **1.3** `test_editor_agent_routing_uses_nvidia_model` — G3
- [x] **1.4** `test_editor_agent_routing_preserves_ollama_models` — G5 (regression)
- [x] Confirm all 4 new tests **fail** before implementation (implicit in the commit history; not independently re-verified)

---

## Phase 2 — `apps/refinery/admin_panel.py`

- [x] **2.1** Change A: Provider-aware Configuration Summary (spec §5.1)
- [x] **2.2** Change B: Ollama sections inside expander when cloud provider active (spec §5.1)
- [x] Run `codacy_cli_analyze` on `admin_panel.py` — re-verified; no new issues (the only SQL finding is pre-existing at the table-wipe block, documented with `# noqa S608 # nosemgrep # nosec`)`

---

## Phase 3 — `news_collector/components/editorial/ai_editor.py`

- [x] **3.1** Change C: Override per-stage models to cloud model when cloud provider active (spec §5.2)
- [x] Run `codacy_cli_analyze` on `ai_editor.py` — re-verified; the pre-existing md5 finding (line 881) was fixed by this work (now sha256), zero findings remain

---

## Phase 4 — Validation

- [x] **4.1** Run `make test` — nvidia routing suite is 20/20 green (repo-wide `make test` has 13 pre-existing unrelated failures tracked separately, none in this file)
- [x] **4.2** Verify acceptance criteria from spec §7 manually in Streamlit — verified 2026-08-05 via AppTest harness against the real `.env` (NvidiaProvider detected; metric cards show the active cloud model; provider radio preselects NVIDIA) plus programmatic routing-check of `EditorAgent`
- [x] Mark spec acceptance criteria as done — completed 2026-08-05
