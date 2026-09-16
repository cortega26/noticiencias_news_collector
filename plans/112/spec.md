# Plan 112: Share UI + hero/OG zero-defect + social-distribution close-out

> **Executor instructions**: Mostly frontend. Mount the dead share component, sweep the top-20 heroes, and close the 4 deferred social items (no new distribution design). Update the `112` row in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> Frontend `git diff --stat HEAD -- src/layouts/PostLayout.astro src/components/template/common/ src/pages/social-manifest.json.ts scripts/dist-sanity.js docs/`; backend `git diff --stat HEAD -- docs/PIPELINE_CONTRACTS.md` (expect plan-081 activity — do not fight it).

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: None; Wave 2 — parallel-safe with 111 (FE template vs BE policy)
- **Category**: engagement/looks
- **Planned at**: backend `9fa77b6`, 2026-09-16 (frontend work in `../noticiencias`)

## Why this matters

`SocialShare.astro` + its `BasicScripts` click handler exist but have zero imports — articles ship with no share UI. OG/hero defects silently kill social CTR. The social-distribution MVP is live on Buffer (run 34897448358, 3 channels) with 4 small deferred items that keep it fragile.

## Current state (verified)

- `FE src/components/template/common/SocialShare.astro:1-69` (5 buttons) + `ds/templates/BasicScripts.astro:88-119` handler; `PostLayout.astro` does not import it.
- OG: `config.yaml openGraph 1200x628`, `Metadata.astro + buildHead.ts:22-213`, `images.ts:131-216 optimizeOpenGraphImage`; checks `check:hero-images/image-alt/image-derivatives`, `publish:image-derivatives`.
- Social MVP done: `scripts/social/publish.js (runDistribution)`, `providers/buffer.js` LIVE, `providers/bluesky.js` code-ready no creds, `workflows/social-distribution.yml` gated `SOCIAL_PUBLISH_ENABLED`, `social-manifest.json.ts` + `dist-sanity.js:343-571` + docs in `ARCHITECTURE.md/SOURCE_OF_TRUTH.md`.
- Deferred: Bluesky `BLUESKY_DID/PDS_URL/APP_PASSWORD` missing; `workflow_dispatch reconcile` hardcodes `--execute`; no `docs/runbooks/social*.md` (runbook = `operate.js --help`); BE `PIPELINE_CONTRACTS.md social` line left for operator (plan-081 collision).

## Scope

**In scope**: mount share UI in `PostLayout` (+copy-link); top-20 hero/alt/derivative sweep; prune dead `Pricing/Testimonials/Brands` widgets (delete + prove `lint/build` green); Bluesky decision (provision creds OR record explicit defer — either closes it); `reconcile` dispatch flag fix; `docs/runbooks/social-distribution.md`; BE contracts doc line only if 081 is not editing that file.

**Out of scope**: new share channels, redesign, new distribution providers, backfill of `social` (forbidden by package-1 spec).

## Steps

### Step 1: Share UI + hero sweep (frontend)
Import `SocialShare` in `PostLayout` (idempotent under Astro `ClientRouter` navigations), add copy-link, verify unfurls (og:title==manifest, canonical==og:url per dist-sanity). Fix top-20 hero/alt/derivative failures; delete dead widgets.

**Verify**: `npm run validate:content + lint + build + test:dist + test:e2e` green; unfurl spot-check notes.

### Step 2: Social close-out (frontend)
Bluesky creds provisioned or defer recorded with reason; `reconcile` mode reaches the CLI; runbook written; `dist-sanity` still green.

**Verify**: dry-run distribution green; `npm run check:contract-sync --strict` green (no schema change expected).

### Step 3: Backend doc line (conditional)
If and only if plan 081 is not touching `docs/PIPELINE_CONTRACTS.md`, add the `social` field line. Otherwise record the pointer in close-out and skip.

**Verify**: `make docs-check` green.

## Verification (full gate)

| Purpose | Command | Expected |
|---|---|---|
| Ledger (backend) | `.venv/bin/python scripts/validate_plans_ledger.py` | OK |
| Frontend | `npm run validate:content && npm run lint && npm run build && npm run test:dist && npm run test:e2e && npm run check:contract-sync` | exit 0 |
| Backend (if docs touched) | `make docs-check` | exit 0 |

## STOP conditions

- STOP if mounting share UI needs bypassing `Metadata.astro` (pages must not bypass that path per FE source of truth) — integrate through it.
- STOP if BE `PIPELINE_CONTRACTS.md` is under active edit by 081 — skip Step 3, record pointer.

## Git workflow

- Branches: frontend `advisor/112-share-hero-social`, backend docs (if any) `advisor/112-social-docline`.
- Commit example: `feat: article share UI and social-distribution close-out`.
