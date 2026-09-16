# Plan 111: Health block-lite + semantic dedup MVP

> **Executor instructions**: Tighten the trust gate only where it matters (health) and add cross-source grouping without a vector DB. Pure policy code stays I/O-free (LAW-B4). Update the `111` row in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat HEAD -- news_collector/components/editorial/ news_collector/collectors/ news_collector/utils/dedupe.py news_collector/storage/article_repository.py config.toml config/prompts.yaml docs/EDITORIAL_MODES.md`.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (false positives could hide distinct stories; gate changes could block legit publishes)
- **Depends on**: None; Wave 2 — parallel-safe with 112 (BE policy vs FE template, disjoint files)
- **Category**: quality/trust
- **Planned at**: backend `9fa77b6`, 2026-09-16

## Why this matters

The auditor is advisory everywhere (`blocking=false`, 20% sample) — a fabricated health claim and a typo get the same treatment. And dedup is near-exact only (`simhash_threshold=10`): the same finding on Nature, Science, and Phys.org publishes as three stories, diluting the feed. Both are the documented top quality levers.

## Current state (verified)

- Auditor: `components/editorial/auditor.py:68-94`, `config.toml [editorial_auditor]` (enabled, 0.2, non-blocking, timeout 45/20 CI); `refinery_engine.py:195-203,994-1014` single-worker non-blocking; triggers (health categories + sensitive keywords + random sample) per `docs/editorial_quality_system.md`.
- Fact-check: `ai_editor.py` Stage-7 (`_verify_fact_check_claims`, per-claim LLM calls, infra failure → `uncertain`, only verifier-`disputed` blocks via `editorial_fact_check_disputed`).
- Dedup: `utils/dedupe.py` simhash64 + hamming, `article_repository.py:37-176,503-608` prefix-bucketed candidates + cluster assignment; zero embedding/semantic code; `GET /v1/articles/{id}/related` = cluster equality only.

## Scope

**In scope**: (a) block publication on verifier-`disputed` for Health/Medicine/Biology + trigger-word articles only (everything else stays advisory); (b) title+summary similarity grouping, MinHash/simhash-family first (no new infra/DB) → 1 master + N sources surfaced in triage; embedding-based similarity only behind plan 080's deferred-decision gate (labeled cross-language benchmark) — never silently; FP-rate logging.

**Out of scope**: vector DB, changing simhash production behavior (additive grouping only), blocking non-health categories, LLM translation guardrails (deferred — cost).

## Steps

### Step 1: Health block-lite (implemented as escalation, not narrowing)

Finding during implementation: the verifier-disputed gate already blocks
ALL categories, so "block disputed for health only" would have weakened
it. Instead: keep the universal disputed block untouched, and escalate
the plan-083 overclaim detector (advisory `logger.warning`) to a hard
`editorial_capability_overclaim` block inside health scope only.
Non-health behavior is byte-identical to before.

**Verify**: unit tests (disputed-health blocks, disputed-tech passes advisory, uncertain never blocks, infra-failure never blocks); existing auditor tests green.

### Step 2: Semantic grouping MVP
Additive similarity pass over title+summary (MinHash/simhash-family; embeddings only if plan 080's benchmark gate is met) producing groups (master + members) with confidence; surface in triage queue; log merge rate + sampled FP rate. No schema change unless unavoidable — prefer runtime grouping first.

**Verify**: golden test (3 near-duplicate cross-source stories → 1 group) + distinct-but-similar stories stay separate; `make test` green.

### Step 3: Metrics + docs
Record merge rate and auditor-block rate; document the health-gate rule in `docs/EDITORIAL_MODES.md` (same PR — docs follow code per §9).

**Verify**: `make docs-check` green.

## Verification (full gate)

| Purpose | Command | Expected |
|---|---|---|
| Ledger | `.venv/bin/python scripts/validate_plans_ledger.py` | OK |
| Baseline | `make lint && make type && make test` | exit 0 |
| Contracts | `make test-contracts` | exit 0 |
| Publication | `make quality-gate` | exit 0, snapshots untouched |

## STOP conditions

- STOP if grouping needs a vector DB, new service, or migration — re-scope to the additive MVP.
- STOP if the gate blocks any currently-passing golden article outside health scope — the rule is too broad.

## Git workflow

- Branch: `advisor/111-health-gate-semantic-dedup`.
- Commit example: `feat(editorial): health-only disputed block and similar-story grouping`.
