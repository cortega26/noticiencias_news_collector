# Strategic Feature Recommendations (2026)

**Author:** Principal Product Engineer  
**Context:** `noticiencias_news_collector`  
**Objective:** Maximum Net Value (ROI) with strict resource constraints.

---

## 1. Feature Candidates — Forced Ranking

### 1. **"Dead Source" Circuit Breaker & Health Dashboard**

- **Problem:** When a source (RSS/Site) goes down or changes schema, we waste thousands of retry cycles (API & Compute cost) and pollute logs. Operators rely on "noise" to detect failures.
- **Beneficiary:** Operators, Business (Cost Savings).
- **Concrete Value:** Automatically pauses ingestion from failing sources for `X` hours. Reduces error rate by ~90% during outages.
- **Why this slot:** Lowest effort for highest operational stability. "Stop the bleeding" feature.
- **Effort:** **S**
- **Ongoing Cost:** Negligible.
- **Gain:** Reliability, Trust.
- **Implementation:**
  - Components: `RSSCollector`, `DatabaseManager` (Source Status Table).
  - Signal: Consecutive failure count > threshold -> Status=`COOLED_DOWN`.
  - Metric: % of HTTP requests serving useful content vs errors.

### 2. **Refinery "Flash-Triage" UI**

- **Problem:** Editors currently view raw database rows or JSON. Reviewing 50 articles takes ~2 hours.
- **Beneficiary:** Editors.
- **Concrete Value:** Reduces review time per article from ~2 mins to ~10 seconds.
- **Why this slot:** The "human bottleneck" checks quality. If we can't review faster, scaling ingestion is useless.
- **Effort:** **M**
- **Ongoing Cost:** Low (Streamlit page maintenance).
- **Gain:** Velocity, Data Quality.
- **Implementation:**
  - Components: `admin_panel.py`.
  - Signal: "Approve/Reject" buttons with hotkeys (Space/Del).
  - Metric: Articles reviewed per editor-hour.

### 3. **Semantic Deduplication Engine**

- **Problem:** "Breaking Science News" often appears on _Science_, _Nature_, and _Phys.org_ simultaneously. We publish 3 slight variations of the same finding, diluting reader attention.
- **Beneficiary:** Readers, Editors.
- **Concrete Value:** Groups 3 duplicate stories into 1 "Master" story with 3 sources. Improves feed density.
- **Why this slot:** Increases perceived quality of the product significantly.
- **Effort:** **M** (using simple MinHash or local embeddings, no heavy vector DB).
- **Ongoing Cost:** Medium (Compute for embeddings).
- **Gain:** User Experience.
- **Implementation:**
  - Components: `IngestionPipeline`.
  - Signal: Cosine similarity of Title + Summary.
  - Metric: % of ingested articles flagged as duplicates.

### 4. **Structured "Translation-Quality" Guardrails**

- **Problem:** LLM translations occasionally drop context, hallucinate, or fail JSON formatting, breaking the frontend rendering.
- **Beneficiary:** Readers, Trust.
- **Concrete Value:** Enforces output schema (JSON-mode) and runs a cheap "Critic" pass (LLM) to verify translation fidelity before saving.
- **Why this slot:** Prevents embarrassing "garbage text" on production.
- **Effort:** **M**
- **Ongoing Cost:** High (Double Token cost for Verification).
- **Gain:** Trust, Reliability.
- **Implementation:**
  - Components: `OllamaIntegration`.
  - Signal: Pydantic Validation + "Critic" Score.
  - Metric: % of published articles requiring post-publish edits.

### 5. **Public "Verify Source" Badge**

- **Problem:** Scientific verification is our USP. currently, readers just see text.
- **Beneficiary:** Readers (Growth).
- **Concrete Value:** calculated "Trust Score" displayed on Frontend based on Source Domain Authority + Citation Count in text.
- **Why this slot:** Distinguishes `noticiencias` from generic aggregators. Drives "Trust" brand.
- **Effort:** **L**
- **Ongoing Cost:** Low.
- **Gain:** Revenue / Growth.
- **Implementation:**
  - Components: `ScoringEngine`.
  - Signal: Heuristic score based on `source_reliability` \* `citation_count`.
  - Metric: Click-through rate on "High Confidence" vs "Low Confidence" stories.

---

## 2. Explicit Trade-Offs

| Feature               | NOT Building           | Risk                                                   | Assumption                           |
| :-------------------- | :--------------------- | :----------------------------------------------------- | :----------------------------------- |
| **Circuit Breaker**   | Real-time retries      | We miss a "flaky" story that succeeds on 10th try.     | Sources are binary (Up/Down) mostly. |
| **Flash-Triage**      | Advanced Filtering     | Editors might miss context by skimming too fast.       | Speed > Deep analysis for triage.    |
| **Semantic Dedup**    | Vector Database search | False positives (hiding distinct but similar stories). | Local embeddings are "good enough".  |
| **Translation Guard** | Faster Ingestion       | 2x Cost/Latency per article.                           | Quality > Quantity.                  |
| **Verify Badge**      | User Comments system   | Users might gamify or mistrust the score.              | We can heuristic 'trust' accurately. |

---

## 3. Scoring Matrix

| Feature                  | Impact (1-5) | Effort (1-5) | Confidence (1-5) | Leverage (1-5) | **Priority Score** |
| :----------------------- | :----------: | :----------: | :--------------: | :------------: | :----------------: |
| **1. Circuit Breaker**   |      4       |      1       |        5         |       5        |      **100**       |
| **2. Flash-Triage**      |      5       |      2       |        5         |       4        |       **50**       |
| **3. Semantic Dedup**    |      4       |      3       |        4         |       3        |       **16**       |
| **4. Translation Guard** |      5       |      3       |        3         |       2        |       **10**       |
| **5. Verify Badge**      |      3       |      2       |        3         |       2        |       **9**        |

_Note: Score = (Impact × Leverage × Confidence) ÷ Effort_

---

## 4. Final Call

> If only 2 features get built this year, name them and explain why.

**1. Circuit Breaker**: It buys us the operational "sleep at night" stability required to scale. It is the cheapest high-leverage move available.
**2. Flash-Triage**: It unblocks the most expensive resource (Editors). Without this, adding more sources just DDOS-es the human review team.

**Verdict:** Build the **Circuit Breaker** today. It's a localized fix with massive systemic stability gains. Build **Flash-Triage** next week to double editorial throughput.
