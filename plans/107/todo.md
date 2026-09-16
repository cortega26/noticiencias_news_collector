# TODO — Plan 107 (analytics baseline + cost/SLO)

Derived from `spec.md`. Mark when verified, not before.

## Step 0 — Baseline
- [ ] Drift check clean (or drift recorded as STOP)
- [ ] `make lint && make type && make test` green on clean tree (or red recorded)

## Step 1 — GA4 event model (Sprint 0 frontend track)
- [ ] Audit recorded in `docs/analytics-sprint-0.md` (loader, CSP, no prior GA4 confirmed)
- [ ] GA4 ID via config with dev suppression + hostname guard; single init, no duplicate pageviews across ClientRouter
- [ ] Events: page_view+params, article_progress 25/50/75/90 deduped, article_complete (proxy-doc), related_article_click, outbound_click (domain-only), newsletter_cta_view only
- [ ] Engagement + readiness metrics defined; CF baseline recorded with comparison ratios
- [ ] Privacy posture documented; LCP/INP/CLS neutral; unit tests green
- [ ] DebugView/Realtime validation executed; §17 final report (14 items) delivered
- [ ] `npm run build + test:dist + check:search-budget + test:e2e + lint` green

## Step 2 — Cost report (DONE 2026-09-16)
- [x] `scripts/ops/publish_cost_report.py` emits valid JSON on real data
- [x] Unit tests added and passing (7 passed); `ruff`/`black` clean
- [x] Baseline: 20 attempts, success_rate 0.6, failure hotspots frontend_publication_validation (3) + editor_refinement (2); 5 failures carry no failure_class (metering gap, noted)
- [x] critic mean 6.486, words mean 807.3; est ~1.4 metered calls/article (+<=11 nominal); sources 58 (28 full-text / 18 suppressed / 10 summary-only / 2 flaky)
- [x] JSON saved to `reports/publish_cost_baseline.json` (gitignored, local)

## Step 3 — SLO snapshot (DONE 2026-09-16)
- [x] Numbers captured above; `make perf` 8 passed, 2603 deselected, exit 0

## Frontend track — BLOCKED on operator vendor decision (see spec Step 1)
- [ ] ADR-0011 accepted (or GA4 chosen + ADR-0011 superseded) → frontend plan 007 executes in `../noticiencias`
- [ ] Enablement validation + baseline template filled there, not here

## Close-out
- [ ] `validate_plans_ledger.py` → OK
- [ ] `plans/README.md` row 107 updated
