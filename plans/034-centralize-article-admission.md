# Plan 034: Apply one article-admission policy at the collection boundary

> **Executor instructions**: Characterize existing collector behavior before activating configured rejection rules. Centralize admission once; do not add another validation layer. Update plan 034 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- news_collector/collectors news_collector/scoring/basic_scorer.py news_collector/config news_collector/contracts tests/unit/collectors tests/unit/scoring`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/033-make-config-refresh-live.md
- **Category**: bug
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

The base collector contains a configured article validator, but the actual bulk-save path bypasses it and RSS overrides it with only URL/title checks. Scoring separately hardcodes clickbait language. Sources therefore follow different admission rules and configuration can appear active while having no effect.

## Current state

- `news_collector/collectors/base_collector.py:888-930` defines `_validate_article_data()` with title, URL, content, and configured penalty checks.
- `news_collector/collectors/base_collector.py:932+` validates/model-converts bulk articles without invoking that method before persistence.
- `news_collector/collectors/rss_collector.py:949-955` overrides validation with URL/title-only behavior.
- `news_collector/scoring/basic_scorer.py:498-511` embeds a separate clickbait list.
- Existing patterns live in `tests/unit/collectors/test_validation_config.py` and RSS image/collector tests.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Collector tests | `.venv/bin/python -m pytest tests/unit/collectors -q` | all pass with shared-policy cases |
| Scoring tests | `.venv/bin/python -m pytest tests/unit/scoring -q` | all pass without duplicated keyword source |
| Duplicate audit | `rg -n "clickbait|penalty_keywords|_validate_article_data" news_collector/collectors news_collector/scoring` | one policy source plus intentional scoring consumption |
| Full checks | `make lint && make typecheck && make test` | exit 0 |

## Scope

**In scope**: a typed collection-boundary admission result/policy, all collector persistence paths and overrides, configured rule wiring, explicit rejection reasons/metrics, and reuse of the canonical keyword source by scoring where semantically appropriate.

**Out of scope**: changing score weights, introducing ML moderation, retroactively deleting stored articles, source-specific editorial ranking, or making every scoring penalty an admission rejection.

## Git workflow

- Branch: `advisor/034-article-admission-policy`.
- Commit example: `fix(collectors): enforce one admission policy before save`.

## Steps

### Step 1: Characterize current accepted/rejected fixtures

Create table-driven fixtures for empty/short title, invalid URL scheme, missing/short content, configured penalty phrase, valid RSS/HTML/Reddit article, and an editorially undesirable but structurally valid article. Record which change is intentional when the dormant configured policy becomes active.

**Verify**: characterization tests pass against current behavior before the policy switch; expected intentional deltas are explicit in test names.

### Step 2: Define a typed admission decision

Create a narrow module under `news_collector/collectors/` that accepts a normalized `CollectorArticleModel` plus one runtime config snapshot and returns `accepted`, stable reason code, and safe diagnostic fields. Separate structural rejection from scoring penalties; use the config schema's canonical keyword data rather than a copied list.

**Verify**: pure table tests cover every reason, Unicode/case normalization, empty configured lists, and no mutation of input/config.

### Step 3: Apply policy once before duplicate lookup and persistence

Invoke the policy from the shared bulk collection/save boundary after contract normalization and before duplicate checks or database writes. Delete collector overrides that weaken it. Source adapters remain responsible only for parsing/normalization.

**Verify**: each collector integration fixture reaches the same policy once; rejected articles cause zero duplicate queries and zero inserts.

### Step 4: Align scoring terminology and observability

Make `BasicScorer` consume the canonical penalty keyword source if it still needs a soft ranking penalty, while keeping its decision distinct from hard admission. Emit per-reason counters and bounded logs with source ID, never full content.

**Verify**: changing configured keywords via plan 033 affects the next collection/scoring cycle; metrics distinguish hard rejection from soft score penalty.

## Test plan

- Pure policy matrix including boundary lengths, schemes, Unicode/casing, and configuration changes.
- RSS, HTML, and Reddit paths invoke identical admission semantics.
- Rejected inputs perform no persistence/duplicate work.
- Existing valid collector fixtures remain accepted.

## Done criteria

- [ ] Every collector persistence path applies one common policy exactly once.
- [ ] No collector override weakens required fields.
- [ ] Rejection reasons are typed, counted, and safe to log.
- [ ] Scoring and admission share configuration without conflating semantics.
- [ ] Full backend checks pass.

## STOP conditions

- Stop if production-like fixtures show a large unexplained rejection increase; report counts/reasons before enabling the rule.
- Stop if plan 033 has not provided stable per-cycle configuration snapshots.
- Stop if a source contract legitimately permits missing content; model that source-specific normalization explicitly rather than weakening global policy.

## Maintenance notes

New collectors must normalize to `CollectorArticleModel` and rely on the shared boundary. New rejection rules require a reason code, fixture, and rollout impact estimate.

