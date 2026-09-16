# Plan 108: Newsletter capture backend + frontend enablement

> **Executor instructions**: Clone the Worker report pattern (plan 023) for a separate newsletter endpoint. Never POST subscriptions to `/api/report` (different wire contract). Update the `108` row in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat HEAD -- plans/archive/social-distribution/ 2>/dev/null; git status --short | head` (backend) plus frontend `git diff --stat HEAD -- src/config.yaml src/components/common/NewsletterCapture.astro workers/src/`.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (new public endpoint; spam/deliverability)
- **Depends on**: None (Wave 0 — parallel-safe with 107; touches disjoint files)
- **Category**: growth/retention
- **Planned at**: backend `9fa77b6`, 2026-09-16

## Why this matters

`form.newsletter_endpoint` is empty, so `NewsletterCapture.astro` renders an RSS/archive fallback on every surface (`newsletter.astro`, `DailyDesk` aside, temas aside). No email list is being built — the cheapest retention and future sponsorship asset. The `/api/report` Worker (R2 sink, KV rate-limit, idempotency) is the proven template.

## Current state (verified)

- FE `src/config.yaml:76-85`: `form.endpoint='https://noticiencias.com/api/report'` live, `newsletter_endpoint=''` deliberately separate.
- FE `src/components/common/NewsletterCapture.astro:18-19`: `isEnabled=false` → fallback links (`55-70`); enabled branch (`32-55`) is a plain `form POST email`.
- Worker pattern: `workers/src/index.ts:47-73` router, `handlers/report.ts` (bounded body → validate → rate-limit → durable-or-503 → 201+id), `utils/validate.ts + rateLimit.ts`, `wrangler.toml:29-43` R2+KV bindings.
- Blocker: `CommonMeta.astro:11` `form-action 'self'` would block an external POST — must be updated alongside.

## Scope

**In scope**: `POST /api/newsletter` (subscribe/confirm/unsubscribe, double opt-in, idempotent, rate-limited, durable-or-503), new R2/KV bindings + `EMAIL_*` config, `newsletter_endpoint` flip, `form-action` CSP update, footer/post-end capture wiring, runbook docs mirror of `report-pipeline-setup.md`, workerd boundary tests.

**Out of scope**: digest content/scheduling, Buttondown migration, sharing the `/api/report` contract, GA4.

## Steps

### Step 1: Worker newsletter handler (frontend repo)
Create `workers/src/handlers/newsletter.ts` mirroring `report.ts`: bounded body → email-only validation (`validateNewsletter.ts`) → KV fixed-window rate-limit → sha256 idempotency → R2/KV durable write → `201 {message, id}`; `503` when no durable sink. Register `POST /api/newsletter` in `workers/src/index.ts`; add bindings in `wrangler.toml` (new bucket/namespace, never reuse report's).

**Verify**: workerd fetch-boundary tests (valid/oversize/invalid/rate-limited/no-sink) green; `operate`-style `--help` documents the route.

### Step 2: Frontend enablement
Set `form.newsletter_endpoint`, update `form-action` CSP, confirm `NewsletterCapture` renders the real form on `/newsletter/`, footer, post-end, and `DailyDesk`/temas asides. Keep the RSS/archive fallback branch for empty-endpoint (do not delete).

**Verify**: `npm run validate:content`, `npm run test:e2e`, `npm run lint` green in `../noticiencias`.

### Step 3: Contract + runbook docs
Document the wire contract and ops (double opt-in flow, unsubscribe, abuse handling) mirroring `docs/report-pipeline-setup.md`. Add the cross-repo note in backend `docs/PIPELINE_CONTRACTS.md` only if plan 081 is not actively editing that file — otherwise leave a pointer comment in the plan close-out.

**Verify**: `make docs-check` green (backend); frontend `check:doc-drift` exit 0.

## Verification (full gate)

| Purpose | Command | Expected |
|---|---|---|
| Ledger | `.venv/bin/python scripts/validate_plans_ledger.py` | OK |
| Frontend | `npm run validate:content && npm run lint && npm run test:e2e` | exit 0 |
| Backend (docs only if touched) | `make lint && make docs-check` | exit 0 |

## STOP conditions

- STOP if deliverability requires sharing the report endpoint or skipping double opt-in — record and propose Buttondown fallback instead.
- STOP if `validate:content` or workerd tests are red on the clean tree.

## Git workflow

- Branches: frontend `advisor/108-newsletter-capture`, backend docs (if any) `advisor/108-newsletter-docs`. One plan, two repos — land frontend first.
- Commit example: `feat: newsletter subscribe endpoint with double opt-in`.
