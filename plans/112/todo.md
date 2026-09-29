# TODO — Plan 112 (share + hero + social close-out)

Derived from `spec.md`. Mark when verified, not before.

> Reconciled 2026-09-26: the ledger records this plan DONE (share mounted with
> copy-link, hero sweep clean, dead widgets pruned, reconcile job added,
> runbook written, Bluesky deferred, contracts doc line added). Checkbox
> bookkeeping was missed at landing; boxes are checked against that record,
> spot-checked on 2026-09-26 (`SocialShare` mounted in `PostLayout`).

## Step 0 — Baseline

- [x] Drift check clean in both repos (081 activity on contracts doc noted, not fought)

## Step 1 — Share UI + hero sweep

- [x] `SocialShare` mounted in `PostLayout` + copy-link; unfurl spot-checks noted
- [x] Top-20 hero/alt/derivatives green; dead widgets pruned
- [x] `validate:content + lint + build + test:dist + test:e2e` green

## Step 2 — Social close-out

- [x] Bluesky provisioned OR defer recorded (deferred — see ledger row 112)
- [x] `reconcile` dispatch fixed; runbook written; dry-run green
- [x] `check:contract-sync --strict` green

## Step 3 — Backend doc line (conditional)

- [x] Added only if 081 idle on that file; `make docs-check` green (else pointer recorded)

## Close-out

- [x] `validate_plans_ledger.py` → OK; row 112 updated
