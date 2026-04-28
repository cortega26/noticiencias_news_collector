# Todo: Fix NVIDIA Provider Routing

Tracks the implementation described in `spec-nvidia-routing-fix.md`.  
Run `make lint && make test` after each phase.

---

## Phase 0 — Baseline

- [x] Read spec-nvidia-routing-fix.md fully
- [x] Confirm existing test suite passes as-is
- [ ] Create `tests/test_nvidia_routing_fix.py` with failing tests (spec §6)

---

## Phase 1 — Tests (failing first)

- [ ] **1.1** `test_config_summary_shows_nvidia_model_when_nvidia_active` — G1
- [ ] **1.2** `test_ollama_sections_collapsed_when_nvidia_active` — G2
- [ ] **1.3** `test_editor_agent_routing_uses_nvidia_model` — G3
- [ ] **1.4** `test_editor_agent_routing_preserves_ollama_models` — G5 (regression)
- [ ] Confirm all 4 new tests **fail** before implementation

---

## Phase 2 — `apps/refinery/admin_panel.py`

- [ ] **2.1** Change A: Provider-aware Configuration Summary (spec §5.1)
- [ ] **2.2** Change B: Ollama sections inside expander when cloud provider active (spec §5.1)
- [ ] Run `codacy_cli_analyze` on `admin_panel.py`

---

## Phase 3 — `news_collector/components/editorial/ai_editor.py`

- [ ] **3.1** Change C: Override per-stage models to cloud model when cloud provider active (spec §5.2)
- [ ] Run `codacy_cli_analyze` on `ai_editor.py`

---

## Phase 4 — Validation

- [ ] **4.1** Run `make test` — all tests pass
- [ ] **4.2** Verify acceptance criteria from spec §7 manually in Streamlit
- [ ] Mark spec acceptance criteria as done
