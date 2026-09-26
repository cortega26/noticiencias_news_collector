# TODO — Plan 108 (newsletter capture)

Derived from `spec.md`. Mark when verified, not before.

> Reconciled 2026-09-26: the ledger records this plan DONE via frontend plan
> 008 (Buttondown endpoint + CSP + disclosures). **Step 1 was deliberately
> dropped**: the Worker fallback stays unbuilt per ADR-0009, so those boxes
> remain open with a DROPPED marker rather than being falsely checked.

## Step 0 — Baseline
- [x] Drift check clean in both repos (or drift recorded as STOP)
- [x] Frontend `validate:content` green on clean tree

## Step 1 — Worker handler (DROPPED — ADR-0009 chose the frontend Buttondown path)
- [ ] DROPPED: `handlers/newsletter.ts` + `validateNewsletter.ts` created, `/api/newsletter` routed
- [ ] DROPPED: New R2/KV bindings (report bindings untouched)
- [ ] DROPPED: Workerd boundary tests green (valid/oversize/invalid/429/503)

## Step 2 — Frontend enablement
- [x] `newsletter_endpoint` set; `form-action` CSP updated
- [x] Real form renders on newsletter page, footer, post-end, asides
- [x] RSS/archive fallback branch preserved
- [x] `validate:content + lint + test:e2e` green

## Step 3 — Docs
- [x] Runbook/contract docs written; `docs-check` / `check:doc-drift` green

## Close-out
- [x] `validate_plans_ledger.py` → OK
- [x] `plans/README.md` row 108 updated
