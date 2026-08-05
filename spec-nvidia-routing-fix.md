# Spec: Fix NVIDIA Provider Routing — Model Display and Stage Routing

Status: Active  
Scope: `apps/refinery/admin_panel.py`, `news_collector/components/editorial/ai_editor.py`  
Authority: `docs/AGENTS.md`, `docs/ARCHITECTURE.md`

---

## 1. Problem Statement

When NVIDIA NIM is the active LLM provider the system is **functionally using the NVIDIA model** for all LLM calls (because `NvidiaProvider._resolve_model()` detects Ollama model IDs containing `:` and substitutes the configured NVIDIA model). However:

1. **The Streamlit "Configuration Summary" lies.** It shows:
   ```
   Traductor: qwen2.5:32b
   Editor:    qwen2.5:32b
   Titulares: llama3.2:latest
   ```
   These are Ollama per-stage overrides stored in `config.toml [ollama]`. They are irrelevant when NVIDIA is active.

2. **The Presets and Manual Configuration phase-selectors are wrong.** The dropdowns let the user configure Ollama-specific models (`translator_model`, `editor_model`, `headlines_model`) even when NVIDIA is active. Saving those values does nothing useful—the NVIDIA provider ignores them—but the UI implies they matter.

3. **`EditorAgent` logs misleading routing.** The log line:
   ```
   EditorAgent model routing resolved: default=qwen2.5:32b, translator=qwen2.5:32b, ...
   ```
   This is emitted even when NVIDIA is the actual provider. It suggests Ollama models are being used.

4. **`resolve_ollama_model_map` is called unconditionally.** It emits "Resolved Ollama model map" to the log regardless of which provider is active, adding noise and confusion.

---

## 2. Root Causes

| Symptom | Root cause file | Root cause |
|---------|----------------|------------|
| Summary shows Ollama names | `admin_panel.py` lines 637–658 | Summary reads `ollama_cfg` keys without checking active provider |
| Presets/Manual selectors active when NVIDIA | `admin_panel.py` lines 665–742 | Sections always rendered; provider state not consulted |
| `EditorAgent` logs Ollama names | `ai_editor.py` lines 342–375 | `resolve_ollama_model_map` called before provider init; result not overridden after provider is detected |
| Ollama model map always logged | `ai_editor.py` + `model_registry.py` | `resolve_ollama_model_map` called unconditionally |

---

## 3. Goals

**G1 — Correct UI summary**: When NVIDIA or Gemini is active, the Configuration Summary shows the active provider's model for all three stages, not Ollama overrides.

**G2 — Context-aware UI sections**: Presets and Manual Configuration sections are clearly labelled as "Ollama fallback settings" and visually de-emphasised (shown inside an expander) when NVIDIA or Gemini is active.

**G3 — Correct EditorAgent routing log**: When NVIDIA (or Gemini) is active, the routing log shows the actual provider model, not Ollama model names.

**G4 — No new public API changes**: Do not change method signatures visible to callers outside these two files. The fix is internal.

**G5 — Tests pass**: All existing 847+ tests continue passing; new tests verify correct routing.

---

## 4. Non-Goals

- Do not refactor `model_registry.py`. The Ollama model map is still valid for the Ollama fallback path.
- Do not change how NvidiaProvider or GeminiProvider resolve models internally.
- Do not change `config.toml` schema or add new config fields.
- Do not gate the Ollama sections behind a boolean config toggle.

---

## 5. Implementation Plan

### 5.1 `apps/refinery/admin_panel.py`

**Change A — Provider-aware Configuration Summary**

Current code (lines 637–658) reads `ollama_cfg` keys directly.

Replace with:
```python
# When cloud provider is active, all stages use that provider's model
if isinstance(temp_provider, (NvidiaProvider, GeminiProvider)):
    cloud_model = getattr(temp_provider, "model", "N/A")
    r_trans = r_edit = r_head = cloud_model
else:
    r_trans = ollama_cfg.get("translator_model") or base_model_sel
    r_edit  = ollama_cfg.get("editor_model")     or base_model_sel
    r_head  = ollama_cfg.get("headlines_model")  or base_model_sel
```

The `is_heavy_model()` delta logic is unchanged; it will evaluate to `False` for NVIDIA cloud model IDs (they contain no `32b`/`70b`/etc. suffix).

**Change B — Ollama sections inside expander when cloud provider is active**

Wrap the Presets and Manual Configuration sections in a conditional:
- If NVIDIA or Gemini active: render inside `st.expander("⚙️ Configuración Ollama (Fallback — inactivo cuando NVIDIA/Gemini está en uso)", expanded=False)`
- If Ollama active: render normally, no expander wrapper

The variable `active_provider_is_ollama` is already set in the provider-detection block (from the previous fix to this file).

### 5.2 `news_collector/components/editorial/ai_editor.py`

**Change C — Provider-aware model routing in `EditorAgent.__init__`**

After:
```python
self.provider = get_provider(config=cfg, api_url=self.api_url, model=self.model, timeout=3600)
```

Add:
```python
# When a cloud provider is active, override all stage models to that provider's model.
# The Ollama-specific per-stage names (translator_model etc.) are irrelevant for
# cloud providers and would only appear in misleading log lines.
from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider
from news_collector.infrastructure.llm.gemini_provider import GeminiProvider
if isinstance(self.provider, (NvidiaProvider, GeminiProvider)):
    cloud_model = getattr(self.provider, "model", self.model)
    self.model = cloud_model
    self.translator_model = cloud_model
    self.editor_model = cloud_model
    self.headlines_model = cloud_model
```

This means the routing log will correctly show:
```
EditorAgent model routing resolved: default=qwen/qwen3-next-80b-a3b-thinking, translator=qwen/qwen3-next-80b-a3b-thinking, ...
```

**Impact on call sites**: `provider.generate(..., model=self.translator_model)` etc. will now pass the NVIDIA model ID directly instead of the Ollama name. `NvidiaProvider._resolve_model()` will pass through `org/model-slug` format unchanged (correct). **No behavior change at the API call level** — the same NVIDIA model is used.

---

## 6. Verification Plan

Each goal has at least one automated test.

### G1 – UI Summary

**Test**: `tests/test_nvidia_routing_fix.py::test_config_summary_shows_nvidia_model_when_nvidia_active`

When `temp_provider` is a `NvidiaProvider` instance, `r_trans`, `r_edit`, and `r_head` all equal the NVIDIA model name — not any Ollama config value.

*Strategy*: Mock the UI state dicts and assert the summary values.

### G2 – UI Sections

**Test**: `tests/test_nvidia_routing_fix.py::test_ollama_sections_collapsed_when_nvidia_active`

When NVIDIA is active, `active_provider_is_ollama` is `False`, so the expander wrapper is used.

*Strategy*: Assert the `active_provider_is_ollama` boolean derived from provider type.

### G3 – EditorAgent routing log

**Test**: `tests/test_nvidia_routing_fix.py::test_editor_agent_routing_uses_nvidia_model`

When `get_provider()` returns a `NvidiaProvider`, `EditorAgent.translator_model`, `.editor_model`, and `.headlines_model` all equal the NVIDIA provider's model, not Ollama names.

*Strategy*: Construct an `EditorAgent` with mocked provider, assert model attributes.

### G4 – No regressions

Run `make test` (847+ tests must pass).

### G5 – Ollama path unchanged

**Test**: `tests/test_nvidia_routing_fix.py::test_editor_agent_routing_preserves_ollama_models`

When `get_provider()` returns an `OllamaProvider`, per-stage models retain their Ollama-specific values.

---

## 7. Acceptance Criteria

- [x] Running `make refinery` and clicking "Iniciar Recopilación" produces logs with the NVIDIA model in the EditorAgent routing line. (Verified 2026-08-05: `EditorAgent model routing resolved: default=qwen/qwen3-next-80b-a3b-instruct, translator=...enrichment=...` when NVIDIA is configured.)
- [x] The Streamlit Configuration Summary shows `qwen/qwen3-next-80b-a3b-thinking` (or active NVIDIA model) in all three metric cards when NVIDIA is active. (Verified 2026-08-05 via AppTest against the real `.env`: cards 1-3 show `qwen/qwen3-next-80b-a3b-instruct` with delta `Cloud`.)
- [x] The Presets and Manual Config sections are collapsed/de-emphasised when NVIDIA is active. (Verified 2026-08-05: with NVIDIA active the page opens in the Cloud branch; the Ollama Presets/Manual sections live in the separate Local branch.)
- [ ] `make test` passes with 0 failures.
- [x] `codacy_cli_analyze` on changed files produces no new issues. (Verified 2026-08-05 with opengrep against pre-fix baseline `5cde827`: no new findings in `admin_panel.py`/`ai_editor.py`; the pre-existing `md5` finding in `ai_editor.py` was actually fixed to `sha256`.)
