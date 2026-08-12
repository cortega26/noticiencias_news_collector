# Todo: Fix LLM health check (NVIDIA) + scoring weights save

Tracks the implementation described in `spec-llm-health-weights-fix.md`.
Run `make lint && make type && make test` after each meaningful phase.

---

## Phase 0 — Baseline

- [x] Confirm the 3 relevant test files pass before changes
  (`tests/unit/system/test_llm_preflight.py`,
  `tests/unit/system/test_bootstrap_coverage.py`,
  `tests/unit/refinery/test_save_toml_config.py` → 53 passed).

## Phase 1 — Health check uses full Config

- [x] Change `bootstrap.py:259` default to `config_settings.get_config()`.
- [x] Add regression tests in `tests/unit/system/test_llm_preflight.py`:
      (i) config-less `_verify_llm_health` uses the full Config (nvidia
      api_key visible to the checker → available True); (ii) an explicit
      config argument wins over `get_config()`.
- [x] Run `test_llm_preflight.py` → 3 passed.

## Phase 2 — Weights balanced before save

- [x] Add `SCORING_WEIGHT_KEYS` + pure `_balance_scoring_weights` +
      `_on_weight_slider_changed` in `admin_panel.py`.
- [x] Rewrite the weights sliders block to rebalance on any slider change
      (`on_change` handlers + `w_*` widget keys, values copied into
      `config_data["scoring"]["weights"]` for the save button).
- [x] Add unit tests in `tests/unit/refinery/test_balance_scoring_weights.py`
      (preserve moved value, proportional scaling, degenerate inputs,
      unknown key, satisfies validate_config).
- [x] Run `test_balance_scoring_weights.py` + `test_save_toml_config.py` +
      `test_llm_preflight.py` → 16 passed.

## Phase 3 — Validation & handoff

- [ ] `make lint && make type && make test` clean.
- [ ] Manual: confirm a weight edit + save persists to `config.toml` and the
      NVIDIA-health-only warning sequence disappears.
- [ ] Update `plans/README.md` state if applicable (no plan owns this work —
      standalone task).
