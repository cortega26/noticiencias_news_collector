# Plan 107: Audience analytics (Sprint 0 absorbed) + cost/SLO dashboard

> **Executor instructions**: Measure first. No product behavior changes except additive analytics. This plan absorbs the external "Sprint 0 — Audience Analytics & Publisher Monetization Readiness" prompt as its frontend track. **Premise corrections (verified 2026-09-16, do not re-litigate):** GA4 is NOT in production (`src/config.yaml` id `null`, zero `G-` IDs, zero custom dimensions, no prior sprint doc) — Sprint 0 §1's "preserve working GA4" does not apply; implement per its event model instead. No newsletter backend exists — Sprint 0 §6.7 applies to CTA-view events only until plan 108 lands. Update the `107` row in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat HEAD -- src/config.yaml src/components/template/common/Analytics.astro news_collector/monitoring/ news_collector/perf/ 2>/dev/null; git status --short | head`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: None (Wave 0 — runs first, parallel-safe with 108)
- **Category**: observability
- **Planned at**: backend `9fa77b6`, 2026-09-16

## Why this matters

Frontend analytics is wired but dead (`src/config.yaml` `analytics.id: null` → `Analytics.astro` renders nothing), and per-article LLM cost is unknown (headline critic = up to 6 calls/article, fact-check = 1 call/claim, auditor = +20% publishes). Every later plan (108–114) needs these numbers to prove impact, and monetization experiments (113) need a credible audience baseline first. Operator-supplied Cloudflare baseline (recorded below) shows material human traffic with a large automation share — Sprint 0's job is to measure the browser audience cleanly enough to separate publisher behavior from raw HTTP activity.

## Operator Cloudflare baseline (do not lose — comparison input for Step 1)

- 30d: 156,562 total requests / 115,790 human (74%); 13,890 total visits / 8,238 human (59%).
- 7d: 5,271 total visits / 2,624 human (50%).
- Non-human traffic is NOT automatically malicious (search/AI crawlers, feed processors, monitoring, scanners). Do not block crawlers to improve percentages; do not add aggressive WAF rules in this plan. Measurement problem ≠ traffic-quality problem ≠ security problem.

## Current state (verified)

- FE `src/config.yaml:71-74`: `analytics.vendors.googleAnalytics.id: null`; `src/components/template/common/Analytics.astro:1-32` no-ops; CSP in `CommonMeta.astro:11` already allows gtag hosts.
- BE costs: `config.toml [ollama]/[gemini]/[nvidia]`, `max_headline_retries=2` (`ai_editor.py:479-491,1372-1417`, Stage-5 uncached), fact-check per-claim calls (`ai_editor.py:2290-2515`), auditor `sampling_rate=0.2, blocking=false` (`config.toml:530-536`).
- Throughput ceiling: `config.toml [collection]` 12h cadence, `max_concurrent_requests=1`, `max_concurrent_sources=10`, `max_articles_per_source=5`.

## Scope

**In scope**: privacy-friendly analytics enablement (Plausible, NOT GA4 — avoids consent-banner scope); `$published_article` cost report (LLM calls x model, headline retries, fact-check claims, auditor runs); SLO snapshot (ingest success %, dead-source %, PR validation pass %, `make perf` baseline into `reports/perf/`).

**Out of scope**: GA4, consent banner, any collector/scoring/publish behavior change, alerting/paging.

## Steps

### Step 1: Frontend analytics execution lives in the frontend repo (this plan tracks, does not duplicate)

Ownership (decided 2026-09-16 after the frontend spike findings): the Cloudflare Web Analytics build is frontend plan 007 (`../noticiencias/plans/007-analytics-build.md`), gated on ADR-0011 acceptance. This backend plan does NOT implement frontend analytics; it records the requirement, the comparison methodology, and the architect recommendation below so the two repos stay consistent.

Architect recommendation (Sr. Software Architect call, pending operator vendor decision): ship Cloudflare Web Analytics first (aggregate-only, matches `privacidad.md`/`transparencia.md` as written, answers the scale/channel/concentration questions 1-4 and 10-12), and defer the Sprint-0 GA4 event model (progress/continuation/outbound depth, questions 5-7 and 9) as a specified follow-up once either (a) a monetization decision is blocked on engagement depth, or (b) human visits sustain ~25k/month. Rationale: at ~8.2k human visits/month the binding constraint is audience scale, not measurement depth; CF WA needs no policy rewrite or consent analysis while GA4 needs both (Chile Ley 19.628 assessment is mandatory either way and stays a deliverable). If the operator picks GA4 instead, the event model specified in the absorbed Sprint 0 (§6-9 as written in this spec's history) becomes the build spec and ADR-0011 must be explicitly superseded — never run both vendors without recording why.

What this backend plan still owns for Step 1: the Cloudflare baseline numbers above (comparison input), the CF↔vendor comparison ratios, and the requirement that enablement (either vendor) ships with DebugView/Realtime validation plus a filled baseline template. The `docs/analytics-sprint-0.md` deliverable belongs to the frontend repo change that enables measurement.

Original Sprint-0 frontend-track detail (event dictionary, engagement formulas, readiness cuts, validation procedure) is preserved in this spec's Step 1 sub-steps below and applies verbatim if GA4 is chosen; under Cloudflare WA only sub-steps 1 (audit), 4 (comparison), and the scale/channel/concentration parts of 3 apply.

GA4 branch detail (applies only if the operator picks GA4 over the recommended Cloudflare WA path): measurement ID comes from the operator via config (never hardcoded); dev/preview traffic must not contaminate production (hostname guard); single initialization path; correct pageviews across Astro `ClientRouter` transitions (no duplicates); CSP already allows gtag hosts — extend only with evidence; no CWV regression; no new tracking libraries.

Sub-steps:

1. **Audit (record, Sprint 0 §4-5).** Baseline already established 2026-09-16: one conditional loader (`Analytics.astro`), no ID, no custom dimensions, no event helpers, CSP pre-allows googletagmanager/google-analytics. Confirm nothing changed; document what exists in `docs/analytics-sprint-0.md`.
2. **Event model (Sprint 0 §6, native GA4 first — no redundant custom events).** Article metadata params only where they add editorial value: `article_id`, `article_category`, `article_topic`, `publication_age_bucket` (never raw titles — cardinality; never alter SEO URLs). `article_progress` at 25/50/75/90, one fire per milestone, no scroll oscillation, no continuous telemetry. `article_complete` optional, documented as behavioral proxy (90% reach), not proof of reading. `related_article_click` (`source_article_id`, `destination_article_id`, `recommendation_location`) — strategically required for continuation rate. `outbound_click` (destination domain only, no query strings; `link_context`, `article_id`). Newsletter: `newsletter_cta_view` only (no signup events until 108 delivers a backend; never send emails to GA4).
3. **Engagement + readiness (Sprint 0 §7-9, measurement only — no ads).** Deep-read rate (p75/views), completion-proxy rate, internal continuation rate, plus native users/sessions/views/views-per-session/engagement-rate/avg-engagement-time/landing/source-medium/device/country. Prepare (do not install) advertising/sponsorship cuts: pageviews, engaged views, articles/session, mobile/desktop, geo, top-article and category concentration, long tail, channel mix.
4. **Cloudflare comparison (Sprint 0 §10).** Record CF 30d numbers above next to GA4 users/sessions/views; diagnostic ratios (CF human visits / GA4 sessions, CF human requests / GA4 views, views per user, deep-reads per view). Never force agreement — different layers.
5. **Privacy + performance (Sprint 0 §11-12).** No PII, no fingerprinting, sanitized URLs; document the consent posture explicitly (assess-and-document is mandatory; adding a banner is a separate decision, not smuggled in). Prove LCP/INP/CLS neutrality.
6. **Tests + validation (Sprint 0 §13-14).** Unit-test metadata generation, milestone dedup, URL sanitization, dev suppression, event-name stability. Run the full frontend gates. Deliver exact post-deploy validation (DebugView/Realtime: page load → event → safe metadata; milestones; related/outbound clicks).
7. **Docs (Sprint 0 §15).** `docs/analytics-sprint-0.md`: architecture, event dictionary, engagement definitions, CF comparison method, privacy rules, validation procedure, filled baseline template. Gaps + anomalies-for-separate-investigation + suggested Sprint 1 experiments (not implemented) close the doc.

**Verify**: `npm run build + test:dist + check:search-budget + test:e2e + lint` green in `../noticiencias`; DebugView procedure executed against preview; final report covers Sprint 0 §17 items 1-14.

### Step 2: Per-article cost report (backend, edge-only per LAW-B4)
New `scripts/ops/cost_report.py` (plus narrow unit tests) aggregating from existing logs/metadata: model calls per publish (drafter/critic/headlines/fact-check/auditor), headline-retry count, publish lead time (collect → PR → live). Read-only over logs/DB; no pipeline changes.

**Verify**: `pytest` new tests pass; report emits valid JSON on a seeded sample; `make lint` clean.

### Step 3: SLO snapshot
Record one baseline row: ingest success %, source-failure %, PR pass %, `make perf` output reference. Store under `reports/` (gitignored-friendly; do not commit large artifacts — commit only the summary if repo convention allows, else keep local and paste numbers into the plan's closing note).

**Verify**: numbers captured; `make perf` exit 0 or clean-skip with `reports/perf/SKIPPED` per `docs/ci.md`.

## Verification (full gate)

| Purpose | Command | Expected |
|---|---|---|
| Ledger | `.venv/bin/python scripts/validate_plans_ledger.py` | OK |
| Backend gates | `make lint && make type && make test` | exit 0 |
| Perf baseline | `make perf` | exit 0 or clean SKIPPED |
| Frontend | `npm run build && npm run test:dist && npm run check:search-budget` (in `../noticiencias`) | exit 0 |

## STOP conditions

- STOP if baseline `make lint/type/test` is red on the clean tree — record, do not fix-forward outside scope.
- STOP if analytics vendor requires a consent banner or leaks PII — fall back to a different privacy-first vendor, do not ship GA4 silently.

## Git workflow

- Branch: `advisor/107-analytics-cost-slo`.
- Commit example: `chore: enable privacy analytics and cost baseline`.
