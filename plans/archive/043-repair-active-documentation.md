# Plan 043: Make active documentation match the implemented system

> **Executor instructions**: Execute after the listed architecture/contract plans, derive facts from code and workflows, and strengthen automated drift checks. Do not rewrite historical archives as if they were current. Update plan 043 in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat e43bd30..HEAD -- README.md docs/PRODUCT_FLOW.md docs/PIPELINE_CONTRACTS.md docs/security.md docs/SOURCE_OF_TRUTH.md docs/ci.md`
> `git -C ../noticiencias diff --stat 0cdca74..HEAD -- README.md docs/ARCHITECTURE.md docs/SOURCE_OF_TRUTH.md scripts/check-doc-drift.js package.json astro.config.mjs`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/020-enforce-cross-repo-schema-parity.md, plans/021-rebuild-publication-callback-contract.md, plans/023-connect-and-harden-report-pipeline.md, plans/024-canonicalize-backend-dependencies.md, plans/028-enforce-v2-editorial-contract.md, plans/032-migrate-frontend-dependencies.md, plans/039-prebuild-browser-search-index.md, plans/041-add-whole-workspace-verification.md
- **Category**: docs
- **Planned at**: backend `e43bd30`, frontend `0cdca74`, 2026-07-21

## Why this matters

Active onboarding and architecture documents contain incorrect contract paths, framework versions, deployment URLs, callback behavior, compatibility claims, and security workflow names/commands. The frontend drift checker validates only a small document set and mostly path existence, so semantically stale facts pass CI. Contributors need one current, code-derived story for both repositories.

## Current state

- Backend `README.md:63-64`, `docs/PRODUCT_FLOW.md:126+`, and `docs/PIPELINE_CONTRACTS.md` name `../noticiencias/src/content/config.ts`; the real schema is `src/content.config.ts`.
- `docs/PRODUCT_FLOW.md` claims v1 export tolerance, no automatic backend notification, GitHub Pages URLs under `noticiencias.cl/post/...`, and parity on every backend CI run; plans 020/021/028 change or correct these facts.
- `docs/security.md` names nonexistent `audit-security.yml`/`security.yml`, scans old `src core` paths, audits `requirements.txt`, and documents obsolete GHSA exceptions.
- Frontend `README.md:9` calls the installed site Astro 5 despite Astro 6 in the planned-at lock and plan 032's supported migration.
- Frontend `docs/ARCHITECTURE.md:47-53` documents client-built search, which plan 039 replaces; lines 175-177 describe compatibility behavior changed by plan 022.
- Frontend `docs/SOURCE_OF_TRUTH.md:89-92` also embeds search implementation details that must follow plan 039.
- `scripts/check-doc-drift.js` checks five frontend documents, skips markdown table rows/code blocks/cross-repo references, and validates existence/scripts but not version/contract/deployment invariants.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend links/facts | `make docs-check` | active backend paths, commands, workflow names, and generated facts pass |
| Frontend drift | `npm --prefix ../noticiencias run check:doc-drift` | active frontend and cross-repo references pass |
| Stale strings | `rg -n "src/content/config\.ts|static Astro 5|audit-security\.yml|\.github/workflows/security\.yml|noticiencias\.cl/post" README.md docs ../noticiencias/README.md ../noticiencias/docs --glob '!**/archive/**' --glob '!**/audits/**' --glob '!**/migration/**'` | no active stale claims; intentional historical references excluded by named scope |
| Full gates | `make verify-ci && npm --prefix ../noticiencias run verify:ci` | exit 0 |

## Scope

**In scope**: active backend/frontend README, source-of-truth, architecture, product-flow, contracts, security/CI/runbook pages directly contradicted by completed plans, doc indexes, and automated doc fact/path/command checks.

**Out of scope**: archives, dated audits, changelogs, migration logs, translating every document, marketing copy, or documenting plans as completed before their code lands.

## Git workflow

- Branch: `advisor/043-current-system-docs` in both repositories.
- Commit example: `docs: align active system contracts and operations`.
- Keep backend/frontend documentation commits separate but cross-link the same final contract.

## Steps

### Step 1: Build a code-derived truth matrix

After dependencies complete, record exact framework/runtime versions, authoritative schema paths, export version policy, publication/callback states, report endpoint, deploy host/URL shape, search implementation, dependency/security manifests, canonical verification commands, and workflow names from code/config. Mark each active doc paragraph that claims one of these facts.

**Verify**: every matrix fact has a code/workflow source and every known stale string maps to an edit.

### Step 2: Correct the end-to-end system narrative

Update backend README, Product Flow, Pipeline Contracts, security/CI/runbook/source-of-truth material and frontend README/Architecture/Source of Truth. Describe current behavior only; put remaining compatibility/debt in an explicit dated section. Use repository-relative Markdown links, not `/home/carlos/...` absolute paths.

**Verify**: stale-string command has no active matches and link/path checks pass from both repo roots.

### Step 3: Expand doc drift from paths to declared invariants

Extend frontend `check-doc-drift.js` and add/extend the backend equivalent to validate the complete active-doc allowlist, npm/Make commands, workflow filenames, schema paths, configured production site host, package/runtime major versions, and cross-repo references when a sibling/checked-out snapshot is available. Parse authoritative files instead of hardcoding rapidly changing versions twice.

**Verify**: tests/fixtures show each stale class fails with file/line/actionable expected value; current active docs pass.

### Step 4: Declare historical boundaries and ownership

Ensure doc indexes label archives/audits/migrations as historical, identify owners for contract/security/deploy/search facts, and add a review checklist tying code path changes to docs. Do not bulk-edit historical evidence.

**Verify**: changed-file tests require a relevant active doc review when contract/workflow/config paths change, while archive-only edits do not trigger false failures.

## Test plan

- Broken path, missing npm/Make target, nonexistent workflow, wrong schema path, wrong site host, wrong framework major, and stale contract-version fixtures.
- Run doc checks with and without sibling repo checkout/snapshot.
- Markdown link validation and full canonical repo gates.

## Done criteria

- [ ] Active docs describe the implemented post-plan system and use correct relative paths.
- [ ] Security, CI, publication, report, search, deployment, and version claims are current.
- [ ] Automated drift checks catch every stale class found in this audit.
- [ ] Historical documents remain historically intact and clearly non-authoritative.
- [ ] Both repositories' canonical verification gates pass.

## STOP conditions

- Stop if any dependency plan is incomplete; document current shipped behavior, not intended behavior, or defer the affected paragraph.
- Stop if production hostname/deployment authority cannot be established from configuration/workflow; ask the operator rather than guessing.
- Stop if a semantic check requires scraping external services; validate local authoritative config instead.

## Maintenance notes

Prefer generated/version-derived facts over prose duplication. Contract, workflow, framework, host, or search changes must update active docs in the same PR.
