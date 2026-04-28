# Spec: Stabilize Pre-Scoring and Critic Rejection Quality

Status: Active
Scope:
- `news_collector/scoring/pre_scorer.py`
- `news_collector/components/editorial/ai_editor.py`
- focused regression coverage under `tests/`

Authority:
- `docs/AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/SOURCE_OF_TRUTH.md`

## 1. Goals

The current backend shows three coupled failures during collection/refinery runs:

1. `PreScorer` often loses the LLM answer because the model returns prose plus JSON-like output, producing:
   - `Failed to extract JSON from NVIDIA response`
   - `PreScorer: LLM retornó 0 válidos. Rellenando con FIFO.`
2. When the LLM fails, the fallback is FIFO, which tends to keep low-value articles that are weak for a Latin American general-interest science audience.
3. The critic can permanently discard an article with:
   - `Score 0/80.0. Reason: No text provided. Recoverable: False`
   even when the real problem is an empty or broken stage-2 editorial output, not an off-topic source article.

This task fixes those three behaviors without changing the overall pipeline shape.

## 2. Non-Goals

- No source catalog redesign in `sources.yaml`.
- No new global ranking framework.
- No threshold retuning across the full editorial policy surface.
- No provider-wide JSON contract change for every LLM consumer.

## 3. Current Failure Analysis

### 3.1 PreScorer is brittle at the provider boundary

`PreScorer.select_top_candidates()` currently calls the LLM with `json_mode=True` and assumes a clean JSON payload comes back. With reasoning-heavy models, the response can include prose before the JSON payload. When parsing fails, the provider returns an empty structure and `PreScorer` falls back to FIFO.

### 3.2 FIFO fallback is editorially wrong

FIFO preserves feed order, not Noticiencias editorial value. In practice that over-selects:

- hyper-local US campus stories
- minor institutional announcements
- product/fundraising/award items
- niche updates with low LatAm or broad-human relevance

### 3.3 Critic is classifying pipeline failure as content failure

`EditorAgent.process_article()` can send empty or near-empty `final_content` into `_critic_pass()`. The critic LLM then replies with something like `No text provided`, and the current logic trusts `recoverable: false`, causing a permanent discard even though the defect is a recoverable editorial-generation failure.

## 4. Implementation Plan

### 4.1 Harden `PreScorer` locally, not provider-globally

File: `news_collector/scoring/pre_scorer.py`

Changes:

- Stop relying on provider-side JSON extraction for this flow.
- Call the LLM in text mode and parse the response inside `PreScorer`.
- Add a narrow parser that accepts:
  - clean JSON object: `{"selected_indices": [...]}`
  - clean JSON list: `[1, 3, 0]`
  - fenced JSON blocks
  - prose plus trailing JSON/list output
- Keep the boundary local to `PreScorer`; do not widen the generic provider contract.

Why:

- This removes the frequent NVIDIA warning for this path.
- It lets `PreScorer` tolerate reasoning-heavy models without touching other JSON consumers such as the critic or cognitive scorer.

### 4.2 Replace FIFO fallback with deterministic editorial fallback

File: `news_collector/scoring/pre_scorer.py`

Changes:

- Add a local deterministic candidate scorer for fallback and fill-in ordering.
- Rank candidates using signals already available in title/summary/source context:
  - positive:
    - LatAm countries/institutions/geographies
    - science/health/climate/space/AI/public-interest terms
    - evidence/research/study/discovery language
  - negative:
    - campus-event / dean / student / alumni / award / fundraiser language
    - narrow institutional announcements
    - generic product launch / partnership / funding noise
- Use that deterministic rank in two places:
  - to fill missing picks when the LLM returns partial/invalid output
  - to replace feed-order FIFO when the LLM is unavailable, rate-limited, or malformed

Prompt change:

- Tighten the prompt so “relevance” explicitly means:
  - direct LatAm connection, or
  - clear universal interest for a curious Spanish-speaking Latin American reader
- Explicitly down-rank hyper-local institutional news.

Why:

- Even when the LLM fails, the system no longer degrades to feed order.
- This is the smallest change that directly addresses “la mayoría de los artículos son de bajo valor”.

### 4.3 Treat empty editorial output as recoverable before critic discard

File: `news_collector/components/editorial/ai_editor.py`

Changes:

- Add a deterministic pre-critic validation of stage-2 editorial output.
- If the generated content is empty or effectively blank after cleanup:
  - do not classify it as off-topic
  - trigger the existing repair path with a concrete repair reason
  - never mark it irrecoverable on that basis
- Harden `_critic_pass()` so “No text provided” style responses are always normalized to `recoverable=True`.
- Avoid writing clearly empty/broken stage-2 output to cache.

Why:

- “No text provided” is a pipeline artifact, not evidence that the source article is fundamentally off-topic.
- This prevents permanent false negatives and gives the repair loop a fair chance to recover.

## 5. Files Expected To Change

- `news_collector/scoring/pre_scorer.py`
- `news_collector/components/editorial/ai_editor.py`
- new focused tests under `tests/`
- `todo.md`

## 6. Verification

### V1. PreScorer parses mixed NVIDIA-style output

Proof:

- Add a regression test where the LLM returns prose plus a JSON payload whose chosen order differs from heuristic rank.
- Expected result: `select_top_candidates()` preserves the LLM-selected order, proving the mixed response was parsed.

### V2. Fallback ranking is not FIFO

Proof:

- Add a regression test with one LatAm/high-interest science item and several low-value campus/admin items.
- Force the LLM result to be empty/invalid.
- Expected result: the LatAm/high-interest item is selected ahead of the low-value items.

### V3. Partial LLM output is completed with heuristic order

Proof:

- Add a regression test where the LLM returns only one valid index.
- Expected result: the first LLM-selected item is preserved and only the remaining slots are filled by deterministic editorial rank.

### V4. Empty stage-2 output is recoverable

Proof:

- Add an end-to-end `EditorAgent.process_article()` test where:
  - translation succeeds
  - first editorial adaptation returns empty text
  - repair returns valid article markdown
- Expected result: the article is produced successfully and the critic is only called after repairable content exists.

### V5. Critic normalizes “No text provided” as recoverable

Proof:

- Add a targeted critic test with mocked LLM response:
  - `{"score": 0, "reason": "No text provided", "recoverable": false}`
- Expected result: `_critic_pass()` returns `recoverable=True`.

### V6. Required validation gates

Because this is a workflow/editorial/scoring change, run:

```bash
make lint
make type
pytest tests/test_llm_rate_limiter.py tests/test_terminology.py tests/test_editor_agent.py
```

If the new focused tests live elsewhere, include them explicitly in the pytest invocation.
