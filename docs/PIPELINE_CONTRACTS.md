# Pipeline Contracts & Failure Modes

**Version:** 1.0 (Draft)
**Status:** Living Document
**Scope:** News Collector Ingestion $\rightarrow$ Refinery $\rightarrow$ Publishing $\rightarrow$ Auditor

---

## 1. Pipeline Phases & Contracts

### Phase 0: Ingestion Handoff

Transfers collected articles from the autonomous collector to the human-in-the-loop Refinery.

- **Producer:** `news_collector.system.pipeline.run_cycle_orchestration`
- **Consumer:** `apps.refinery.admin_panel` (via `RefineryEngine` or direct load)
- **Artifact Path:** `data/exports/latest_articles.json` (with fallback to `temp/source/...`)
- **Schema:** `news_collector.contracts.export.ExportContractV2`
  - `schema_version`: `2` (int)
  - `articles`: List[`ExportArticleModel`]
- **Failure Mode:** **Fail-Soft**. If the JSON is missing or corrupt, the Refinery currently shows "No articles found" or mock data.
  - _Target Behavior_: **Fail-Safe**. If JSON is invalid, fall back to querying the SQLite DB (`articles` table with `status='pending'`).

### Phase 1: Scientific Translator

Translates technical content to Spanish while preserving scientific accuracy.

- **Implementation:** `ai_editor.EditorAgent._translate_scientific`
- **Input:** Raw text (English/Mixed)
- **Output:** `translated_text` (str)
- **Cache:** `temp/cache/{safe_id}_stage1_translation.txt`
- **Failure Mode:** **Fail-Closed**. Exceptions during LLM call abort the article.

### Phase 2: Editorial Adapter

Adapts tone to "Science Journalist for LatAm" style.

- **Implementation:** `ai_editor.EditorAgent._adapt_editorial`
- **Input:** `translated_text` (from P1)
- **Output:** `final_content` (Markdown str)
- **Cache:** `temp/cache/{safe_id}_stage2_editorial.txt`
- **Failure Mode:** **Fail-Closed**.

### Phase 2.5: The Critic (Quality Guardrail)

Validates content against safety and quality rules explicitly.

- **Implementation:** `ai_editor.EditorAgent._critic_pass`
- **Input:** `final_content` (from P2)
- **Output:** `(bool, reason)`
- **Configuration:**
  - **Threshold:** `TEXT_PROCESSING_CONFIG.critic_score_threshold` (Default: 70)
  - **Max Retries:** 2 (Hardcoded in `process_article`)
  - **Model:** Implicitly uses `editor_model` (No dedicated binding).
- **Logic:**
  1.  Check Spanish language.
  2.  Check Science/Tech relevance.
  3.  Check Proper Nouns against `scientific_entities.json`.
- **Failure Mode:** **Fail-Closed**.
  - If `score < 70` after retries $\rightarrow$ Raise `ValueError`.
  - If LLM crashes $\rightarrow$ Return `False` (Safe Default).
  - _Bypass_: `ENABLE_TRANSLATION_GUARD="false"` env var skips this phase.

### Phase 3: Metadata & Headlines

Generates structured metadata, headlines, and tags.

- **Implementation:** `ai_editor.EditorAgent._generate_headlines`
- **Input:** `final_content`
- **Output:** `HeadlinesSchema` (Dict)
  - `direct`, `question`, `benefit`, `excerpt`, `tags`
- **Failure Mode:** **Fail-Closed**. Schema validation errors abort the process.

### Phase 4: Publishing

Persists the artifact and notifies downstream systems.

- **Implementation:** `refinery_engine.RefineryEngine.process_single_article`
- **Output:**
  1.  **File**: `src/content/posts/{yyyy-mm-dd-slug}.md` (Schema: `AstroPost`)
  2.  **Git**: Branch `content/update/{slug}` + Pull Request
  3.  **DB**: Mark article as `published` with PR URL.
- **Idempotency**: Checked via `refinery_manifest.json` and DB `canonical_slug`.
- **Failure Mode:** **Fail-Closed**. Git errors or IO errors abort the specific article.

### Sidecar: Auditor

Evaluates epistemic rigor asynchronously.

- **Implementation:** `auditor.EditorialAuditor.audit_article_sync`
- **Trigger:** `refinery_engine` submits to `ThreadPoolExecutor` (Max workers: 1).
- **Input:** Refined Content + Metadata.
- **Output:** `data/article_metadata/{safe_id}/auditor_score.json`
- **Schema:** `_get_default_audit_result` (Normalized)
  - `epistemic_rigor_score`: float (0.0 - 10.0)
  - `issues`: list[str]
- **Failure Mode:** **Fail-Open**.
  - Exceptions are logged.
  - Circuit Breaker trips after 3 failures (30 min cooldown).
  - **Does NOT block** the publishing PR.

---

## 2. Reality vs UI Mismatches

| Feature          | Reality (Code)                        | Streamlit UI (Current)                         | Status    |
| :--------------- | :------------------------------------ | :--------------------------------------------- | :-------- |
| **Critic Phase** | **Active** (Checks score > 70)        | **Visible** in "AI Settings" (Status + Config) | ✅ Parity |
| **Critic Model** | Uses `editor_model` (Shared)          | **Visible** ("Usa el mismo modelo...")         | ✅ Parity |
| **Bypass State** | `ENABLE_TRANSLATION_GUARD` env/secret | **Visible** (Warning if Disabled)              | ✅ Parity |
| **Auditor**      | Sidecar / Async                       | **Visible** in "Publicados" (Score + Badge)    | ✅ Parity |
| **Export Error** | JSON missing/corrupt                  | **Handled** (Fallback to DB + Warning)         | ✅ Parity |

**Status:** ALL MISMATCHES RESOLVED.

---

## 3. Operational Playbook

### If Export is Missing

- **Symptom**: Admin Panel shows "⚠️ Export Artifact Corrupt/Invalid..." warning at top of candidate list.
- **Behavior**: The system automatically queries the SQLite DB for articles in `pending` or `new` status and loads them.
- **Action**: Proceed as normal. The fallback is robust. To fix the root cause, run `make collect` to regenerate the JSON.

### If Critic Fails (Too Strict)

- **Symptom**: Articles fail with "Translation Guardrail: Content rejected...".
- **Action**:
  1.  Go to "AI Settings".
  2.  Toggle "Habilitar Crítico" to **OFF** (Warning will appear).
  3.  Reprocess the article.
  4.  Toggle it back **ON** afterwards.

### Interpreting Auditor Scores

- **Location**: "Publicados" Tab, under the article ID.
- **Badges**:
  - 🟢 **Green (> 8.0)**: Use with confidence (High Rigor).
  - 🟡 **Orange (5.0 - 8.0)**: Acceptable for general news.
  - 🔴 **Red (< 5.0)**: Review carefully. May contain speculation or lacks caveats.
