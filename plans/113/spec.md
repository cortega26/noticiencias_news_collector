# Plan 113: Monetization foundations (no extraction)

> **Executor instructions**: Foundations only — pages and docs, zero ad scripts, zero paywall signals. Do not touch `isAccessibleForFree` or the render schema. Update the `113` row in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> Frontend `git diff --stat HEAD -- src/pages/ src/navigation.ts`; backend `git diff --stat HEAD -- docs/ news_collector/serving/api.py`.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (reputational if ads-adjacent copy overpromises — keep it factual)
- **Depends on**: 107 (needs baseline traffic numbers before writing the media kit); Wave 3 — parallel-safe with 114
- **Category**: monetization readiness
- **Planned at**: backend `9fa77b6`, 2026-09-16 (mostly frontend work in `../noticiencias`)

## Why this matters

At 36 posts with no analytics, extraction (AdSense/paywall) would trade trust for cents. But with zero media-kit, zero donate path, and an undocumented ranked-reads API, future money has nowhere to land. This plan builds the landing pad.

## Current state (verified)

- Zero product monetization hits (`adsense|stripe|paywall|patreon|kofi|sponsor` = dependency metadata + article prose only); only `metodologia.md:51` "no vivimos de clics… suscríbete al boletín".
- No `media-kit/sponsor/donate/apoya` routes (23 FE routes audited); footer has no monetization links; `Pricing.astro` exists unreferenced (112 proposes pruning it — coordinate: this plan must not depend on it).
- B2B asset: `GET /v1/articles` public, no key/rate-limit; OpenAPI snapshot `.contract-snapshots/admin_openapi.snapshot.json`; `docs/api_examples.md` exists.
- Red line already stated in `nosotros.md:38` (no government/party/corporate funding conditioning coverage).

## Scope

**In scope**: `patrocinios.md` media-kit draft (audience placeholder wired to 107 numbers, methodology, contact, ethical-sponsor criteria); Ko-fi/Open Collective donate link in footer + `nosotros.md`; ad principle paragraph in `EDITORIAL.md` (ethical sponsors only, never programmatic health-claim ads, `Editorial` stays first-party); B2B one-pager in `docs/api_examples.md` (ranked reads + related endpoint, future paid tier noted, no pricing).

**Out of scope**: any ad/tracking/paywall/donation-widget script, any schema change, any pricing or contract terms, public API rate-limiting (noted as pre-monetization requirement, not built here).

## Steps

### Step 1: Media kit + donate (frontend)
New `src/pages/patrocinios.md` (factual, numbers clearly marked preliminary until 107 data matures), footer link, donate link. Keep tone consistent with `metodologia.md:51`.

**Verify**: `npm run validate:content + lint + build` green; no new third-party scripts (`grep -ri gtag/adsense/stripe` on changed files empty except pre-existing Analytics).

### Step 2: Editorial principle (frontend docs)
One paragraph in `docs/EDITORIAL.md` stating the monetization red line.

**Verify**: `npm run check:doc-drift` exit 0.

### Step 3: B2B one-pager (backend docs)
Document the ranked-reads + related endpoints as a future paid product surface in `docs/api_examples.md`; explicitly note that public rate-limiting + keying must precede any monetization (pointer, not implementation).

**Verify**: `make docs-check` green.

## Verification (full gate)

| Purpose | Command | Expected |
|---|---|---|
| Ledger | `.venv/bin/python scripts/validate_plans_ledger.py` | OK |
| Frontend | `npm run validate:content && npm run lint` | exit 0 |
| Backend docs | `make docs-check` | exit 0 |

## STOP conditions

- STOP if 107 numbers are not yet available — ship the kit with clearly-marked placeholders rather than invented figures. Never invent traffic numbers.
- STOP if any step needs a script tag, schema change, or paywall signal — out of scope by design.

## Git workflow

- Branches: frontend `advisor/113-monetization-foundations`, backend `advisor/113-b2b-onepager` (docs-only, may fold into one if operator prefers).
- Commit example: `docs: monetization foundations without extraction`.
