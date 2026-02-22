# Ollama Model Concordance Audit

Date: 2026-02-22  
Scope: `noticiencias_news_collector` end-to-end model ID resolution, routing, and fallback behavior.

## 1) Inventory (Current Canonical State)

### 1.1 Sources of truth

| Source | Keys | Location |
|---|---|---|
| Primary config | `ollama.model`, `ollama.translator_model`, `ollama.editor_model`, `ollama.headlines_model`, `scoring.llm_model` | `config.toml:11`, `config.toml:15`, `config.toml:80` |
| Schema contract | Same fields + shape validation | `noticiencias/config_schema.py:670`, `noticiencias/config_schema.py:698`, `noticiencias/config_schema.py:470` |
| Env nested overrides | `NOTICIENCIAS__OLLAMA__*`, `NOTICIENCIAS__SCORING__LLM_MODEL` | `noticiencias/config_manager.py:370` |
| Env legacy overrides | `OLLAMA_MODEL`, `OLLAMA_TRANSLATOR_MODEL`, `OLLAMA_EDITOR_MODEL`, `OLLAMA_HEADLINES_MODEL`, `SCORING_LLM_MODEL` | `noticiencias/config_manager.py:388` |
| Canonical resolver | Stage model map + validation + normalization | `news_collector/infrastructure/llm/model_registry.py:123` |

### 1.2 Stage/component routing

| Stage / Component | Canonical model source | Call site | Notes |
|---|---|---|---|
| `default` base model | `ollama.model` | `news_collector/infrastructure/llm/model_registry.py:133` | Missing tag normalized once to `:latest` via centralized policy. |
| `translator` (`EditorAgent`) | `ollama.translator_model` else `ollama.model` | `apps/refinery/main.py:293`, `news_collector/components/editorial/ai_editor.py:65` | Resolved once, logged once per signature. |
| `editor` (`EditorAgent`) | `ollama.editor_model` else `ollama.model` | `apps/refinery/main.py:293`, `news_collector/components/editorial/ai_editor.py:68` | Canonical validation enforced. |
| `headlines` (`EditorAgent`) | `ollama.headlines_model` else `ollama.model` | `apps/refinery/main.py:293`, `news_collector/components/editorial/ai_editor.py:69` | No runtime model-existence fallback. |
| `auditor` (`EditorialAuditor`) | `ollama.model` | `news_collector/components/editorial/auditor.py:103` | Uses registry stage getter; explicit logged fallback only when injected test config is incomplete. |
| `pre_scorer` (`PreScorer`) | `scoring.llm_model` else `ollama.model` | `news_collector/scoring/pre_scorer.py:19` | Previously implicit provider default; now explicit stage model. |
| `scoring` (`CognitiveScorer`) | `scoring.llm_model` else `ollama.model` | `news_collector/scoring/cognitive_scorer.py:62` | Previously ignored `scoring.llm_model`; now honored. |
| `classifier` (`EditorialClassifier`) | `ollama.editor_model` else `ollama.model` | `news_collector/editorial/classifier.py:27` | No implicit provider model. |
| `council` (`EditorialCouncil`) | `ollama.editor_model` else `ollama.model` | `news_collector/editorial/council.py:53` | No implicit provider model. |
| Provider runtime override | Explicit `model=` arg (canonicalized) | `news_collector/infrastructure/llm/provider.py:82` | Validation centralized; malformed values fail fast. |
| Health guard | All resolved stage models checked against `/api/tags` | `news_collector/system/bootstrap.py:228`, `news_collector/system/bootstrap.py:265` | Exact match only; no fuzzy alias matching. |

## 2) Fallback Path Classification

| Path | Previous behavior | Classification | Current behavior |
|---|---|---|---|
| Provider auto-appended `:latest` in multiple places | Silent normalization in `__init__` and payload prep | Must log explicitly and continue | Centralized normalization in registry, log-once (`model_registry.py:96`). |
| Editor stage override missing in local Ollama list | Warn + fallback to legacy model | Must fail fast | Removed model-existence fallback path from `EditorAgent`; malformed config now raises immediately. |
| Bootstrap model check fuzzy matching | Accepted partial aliases (`llama3.2` vs `llama3.2:latest`) | Must fail fast | Exact canonical model matching only (`bootstrap.py:265`). |
| Components instantiated provider with no model | Deferred errors and behavior-level fallbacks | Must fail fast | Explicit per-stage model resolved before provider construction. |
| Legacy flat env support incomplete | Some stage overrides could not be supplied in flat env mode | Must log explicitly and continue | Added explicit legacy mapping for stage + scoring model keys (`config_manager.py:396`). |

## 3) Formal Policy (Allowed vs Forbidden)

### Allowed

- Stage unset -> inherit base model **only** as explicit `source=INHERITED`.
- Missing tag normalization (`llama3.3` -> `llama3.3:latest`) **only** in default mode.
- Provider-side canonicalization only via registry functions (no local string mutations).
- Availability checks can disable LLM in default mode, but only with explicit warnings and health flag updates.

### Forbidden

- Any model selection change that is not represented in the resolved model map.
- Any stage fallback to base/default without explicit `INHERITED` provenance.
- Any bypass of registry policy through ad-hoc `:latest` injection.
- In pinned mode: `:latest` and untagged model IDs.
- In no-warnings mode: any normalization/inheritance/provider canonicalization warning path.

## 4) Canonical Model ID Policy

Policy chosen: **Normalize missing tag to `:latest` in exactly one place**.

Why this policy:
- Existing runtime and tests already relied on untagged inputs (for example `.env` had `OLLAMA_MODEL=llama3.3`).
- Enforcing explicit tags immediately would be a breaking operational change.
- Normalization is now deterministic, centralized, and logged exactly once per `(stage, raw, canonical)` tuple.

Validation rules:
- Empty values fail (`MissingModelConfigurationError`).
- Whitespace in IDs fails (`InvalidModelIdError`).
- IDs must be `<model>:<tag>` after normalization with allowed characters.
- Unknown stage names fail (`UnknownModelStageError`).
- In strict mode (`NOTICIENCIAS_LLM_STRICT=1`): implicit normalization fails (`NonCanonicalModelIdError`).
- In pinned mode (`NOTICIENCIAS_LLM_PINNED=1`): `:latest` and missing tags fail fast.

## 5) Precedence Rules (Deterministic)

1. Environment overrides (`NOTICIENCIAS__*` and mapped legacy vars) win over config file values.  
2. Config file values win over schema defaults.  
3. Stage override path wins over base model path.  
4. If stage override is unset, stage resolves as `INHERITED` from base model.  
5. Every resolved stage records `model_id`, `source`, `raw_value`, `normalized`, `inherited`, and `notes`.

## 6) Auditable Model Map

- Runtime emits one deterministic JSON map per signature through the registry logger.
- Preflight exposes the same JSON map deterministically:
  - `python -m news_collector.infrastructure.llm.preflight --json`

Example JSON fields per stage:
- `stage`
- `model_id`
- `source` (`ENV`, `CONFIG`, `DEFAULT`, `INHERITED`)
- `raw_value`
- `normalized`
- `inherited`
- `notes`

## 7) Preflight & Strict Modes (Optional)

- Config-only preflight (no network):
  - `python -m news_collector.infrastructure.llm.preflight --json`
- Availability preflight:
  - `python -m news_collector.infrastructure.llm.preflight --check-availability`
- CI toggle for availability check:
  - `NOTICIENCIAS_OLLAMA_PREFLIGHT=1`
- Strict startup failure on LLM health/model mismatch:
  - `NOTICIENCIAS_LLM_STRICT=1`
- Pinned mode (no `:latest`, no missing tags):
  - `NOTICIENCIAS_LLM_PINNED=1`
- Zero-warnings mode (fail on normalization/inheritance/provider canonicalization):
  - `NOTICIENCIAS_LLM_NO_WARN=1`

Pinned examples:
- Valid: `llama3.3:70b`, `qwen2.5:32b`
- Invalid in pinned mode: `llama3.3:latest`, `llama3.3`

## 8) Regression Guard Tests Added/Updated

- `tests/unit/infrastructure/llm/test_model_registry.py`
  - Validation, precedence, explicit inheritance metadata, deterministic map output, pinned/strict failures.
- `tests/unit/infrastructure/llm/test_registry_consumer_guards.py`
  - Proves major LLM consumers request stage models through registry paths.
- `tests/unit/test_per_phase_models.py`
  - Editor stage routing now validates canonical IDs and fails fast on malformed overrides.
- Existing provider/public entrypoint tests still pass with centralized policy:
  - `tests/unit/infrastructure/llm/test_provider.py`
  - `tests/test_ollama_fix.py`
  - `tests/test_public_entrypoints.py`

## 9) Stage Coverage Gate (Final Closure)

Mechanism:
- Registry has one authoritative stage schema (`ALL_STAGES`) and exposes `get_all_stages()`.
- `resolve_ollama_model_map` hard-fails if any registered stage is missing from the resolved map.
- Unknown stage lookups fail with remediation text to register the stage in `model_registry.py`.
- A lightweight static test scans literal `get_model_for_stage("<stage>")` calls in `news_collector/` and `apps/` and fails if any stage is unregistered.

Limitations (explicit):
- The static scan intentionally covers literal calls only (regex-based tripwire, not full AST).
- Dynamic stage names are out of scope by design and must be reviewed manually.

Adding a new stage checklist:
1. Add the stage to `ALL_STAGES` in `model_registry.py`.
2. Add/update its `_STAGE_OVERRIDE_PATH` mapping.
3. Add config/env mapping if the stage needs a new dedicated key.
4. Update/extend registry tests so `NO_WARN` and precedence expectations stay explicit.

## 10) Zero-Warnings Gate (Final Closure)

`NOTICIENCIAS_LLM_NO_WARN=1` upgrades warning paths to hard failures:
- Any resolved stage with `normalized=true`.
- Any resolved stage with `source=INHERITED`.
- Any provider non-canonical model warning path (`raw` -> `canonical`).

Recommended CI profile:
- `NOTICIENCIAS_LLM_PINNED=1`
- `NOTICIENCIAS_LLM_NO_WARN=1`

This enforces pinned, explicit, non-inherited model routing with no warning-only drift.
