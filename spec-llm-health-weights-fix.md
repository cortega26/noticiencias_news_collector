# Spec: Fix duplicate LLM health check (NVIDIA) + weights not saved

Status: Active
Scope: `news_collector/system/bootstrap.py`, `apps/refinery/admin_panel.py`
Authority: `docs/AGENTS.md`, `docs/ARCHITECTURE.md`

---

## 1. Problem Statement

Two production-visible bugs were confirmed from `data/logs/collector.log`
(2026-08-06 14:19–14:31):

1. **LLM system disabled despite healthy NVIDIA.** The log shows, seconds apart:
   - `11:59:11 | NVIDIA NIM health check passed ...`
   - `14:31:15 | Ollama preflight missing required model(s): ['qwen2.5:32b']`
   then `35x PreScorer: LLM not available (Disabled)` and heuristic fallback.
   Root cause: `preflight_llm_provider()` passes the **full Config** and
   resolves `NvidiaHealthChecker` (healthy). But `System.initialize()` →
   `check_system_health()` calls `_verify_llm_health()` **without config**,
   which falls back to `settings.refresh_runtime_config()` — a
   `RuntimeConfigSnapshot` that has **no `.nvidia` field**. The resolver
   then falls through to `OllamaHealthChecker`, detects a missing model,
   and flips `LLM_SYSTEM_AVAILABLE=False`. The last check wins → LLM disabled.

2. **Scoring weights cannot be saved.** Editing `[scoring.weights]` recency
   from 0.10 → 0.30 (drag-click in Streamlit) and saving changes nothing.
   Root cause: the four weight sliders are edited independently; after the
   change the sum is no longer 1.0 (e.g. 1.20), and `save_toml_config()` →
   `validate_config()` rejects the write (`scoring.weights must sum to 1.0
   ±0.01`) — so `config.toml` stays at the old value and the run is scored
   with the old weights.

## 2. Root Causes

| Symptom | Root cause file | Root cause |
|---------|----------------|------------|
| LLM disabled with NVIDIA healthy | `bootstrap.py:259` | `_verify_llm_health` defaults to `refresh_runtime_config()` (snapshot), which lacks `.nvidia`; `resolve_health_checker` then selects `OllamaHealthChecker` and fails on a missing model |
| Weights save silently no-ops | `admin_panel.py:1733-1753` + `settings.py:410` | Sliders mutate one weight with no re-balancing; sum leaves 1.0; `validate_config` rejects the whole save |

## 3. Design

### 3.1 Health check (bootstrap.py)

`_verify_llm_health()` must resolve the provider from the **full Config**
(`config_settings.get_config()`), not the runtime snapshot. The snapshot is
the immutable runtime view and intentionally does not carry provider
credentials; the provider resolvers (`resolve_health_checker`,
`NvidiaHealthChecker.check`, etc.) need the full Config. Minimal change:

- `bootstrap.py:259`:
  `active_config = config or config_settings.get_config()`

This also matches `preflight_llm_provider()` which is called with the full
Config in `apps/refinery/main.py` and the collector run — one rule for both
entry points.

### 3.2 Weights (admin_panel.py)

Extract a pure `_balance_scoring_weights(previous, current)` helper so the
sliders always produce a weight set that sums to 1.0. The sliders block
reads each slider, detects the one the cursor moved (largest delta vs. the
previous render), keeps its value, and rescales the other three so the sum
is exactly 1.0 (within rounding tolerance). The balanced values are written
into `config_data["scoring"]["weights"]` and therefore validated and saved
by the existing "Guardar Config Colector" path unchanged.

- Introduce module constant `SCORING_WEIGHT_KEYS`.
- Add pure function `_balance_scoring_weights(previous, current)`.
- Rewrite the sliders block (admin_panel.py:1731–1756) to call it and store
  balanced values into `config_data["scoring"]["weights"]`.

### 3.3 Out of scope

- The leaked secrets in `config.toml` (`github.token`, `nvidia.api_key`)
  and the absolute paths written by the panel are tracked as a separate
  session item, not here.
- `HeuristicScorer`/`PreScorer` recency-blind ranking (old articles listed)
  is tracked separately.
- The stale `DEBUG` prints in `scoring/__init__.py` / `cognitive_scorer.py`
  are log-noise cleanup, tracked separately.

## 4. Acceptance Criteria

- `_verify_llm_health` with no config and a full config that has `nvidia`
  resolves `NvidiaHealthChecker` and sets `RUNTIME.llm_system_available=True`.
- `_balance_scoring_weights`: single weight moved → others rescaled to sum
  exactly 1.0 (within tolerance), the moved weight preserved.
- `save_toml_config` can persist a balanced weight set.
- The reported warning sequence (missing qwen2.5:32b) no longer appears when
  NVIDIA is configured; only NVIDIA health is checked.

## 5. Verification

- `make lint && make type && make test`
- New targeted tests:
  - `tests/unit/system/`: `_verify_llm_health` uses the full config
    (nvidia present → available True); default no-config path.
  - `tests/unit/refinery/`: `_balance_scoring_weights` unit behavior.
