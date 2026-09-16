# TODO — Plan 108 (newsletter capture)

Derived from `spec.md`. Mark when verified, not before.

## Step 0 — Baseline
- [ ] Drift check clean in both repos (or drift recorded as STOP)
- [ ] Frontend `validate:content` green on clean tree

## Step 1 — Worker handler
- [ ] `handlers/newsletter.ts` + `validateNewsletter.ts` created, `/api/newsletter` routed
- [ ] New R2/KV bindings (report bindings untouched)
- [ ] Workerd boundary tests green (valid/oversize/invalid/429/503)

## Step 2 — Frontend enablement
- [ ] `newsletter_endpoint` set; `form-action` CSP updated
- [ ] Real form renders on newsletter page, footer, post-end, asides
- [ ] RSS/archive fallback branch preserved
- [ ] `validate:content + lint + test:e2e` green

## Step 3 — Docs
- [ ] Runbook/contract docs written; `docs-check` / `check:doc-drift` green

## Close-out
- [ ] `validate_plans_ledger.py` → OK
- [ ] `plans/README.md` row 108 updated
