# Plan 047: Spike a closed-loop reader correction workflow

> **Executor instructions**: Execute this as a bounded product/architecture spike after plans 021 and 023. Produce a build/no-build decision and tested contract prototype; do not create a production editorial queue or store real reporter data. Update plan 047 in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat e43bd30..HEAD -- news_collector/contracts/webhook.py news_collector/serving/webhook_handler.py news_collector/logic/workflows/publication_identity.py apps/refinery/published_content.py docs tests/fixtures`
> `git -C ../noticiencias diff --stat 0cdca74..HEAD -- src/components/template/widgets/ReportForm.astro workers/src workers/tests tests/playwright docs`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM
- **Depends on**: plans/021-rebuild-publication-callback-contract.md, plans/023-connect-and-harden-report-pipeline.md
- **Category**: direction
- **Planned at**: backend `e43bd30`, frontend `0cdca74`, 2026-07-21

## Why this matters

The workspace has the beginnings of a valuable trust loop: readers can report problems, published posts carry stable Refinery identity, and the backend understands frontend publication events. What is missing is an evidence-preserving path from a report to triage, a correction PR, a visible correction record, and closure. A small contract/state-machine spike can test whether that loop is operationally worthwhile before building queue infrastructure.

## Current state

- Frontend `ReportForm.astro` collects an affected URL, problem type, explanation, and evidence. At the planned-at revision its camelCase fields/problem types disagree with Worker snake_case validation, and an empty endpoint simulates success; plan 023 owns that repair.
- `workers/src/handlers/report.ts:29-77` generates a report UUID, optionally writes R2/sends email, and returns 201 even when both delivery paths are unavailable or fail. It has no triage/correction state.
- `workers/src/utils/validate.ts:11-92` accepts optional reporter email and evidence URL but has no immutable published identity, consent/retention fields, deduplication key, or status capability.
- Backend `PublicationIdentityResolver` and `PublishedArticleRecord` preserve canonical slug, filename, and optional `refinery_id`; this can link a public URL to source identity without trusting a user-supplied database ID.
- Backend webhook contracts currently model validation/publish events keyed largely by branch, not reader reports or correction lifecycle; plan 021 establishes reliable publication correlation first.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Contract prototype | `.venv/bin/python -m pytest tests/spikes/test_reader_correction_contract.py -q` | lifecycle, identity, idempotency, and redaction fixtures pass |
| Worker compatibility | `npm --prefix ../noticiencias/workers test` | report intake remains compatible after plan 023 |
| Frontend form smoke | `npm --prefix ../noticiencias run test:e2e -- tests/playwright/report-form.test.ts` | configured intake success/failure behavior passes |
| Documentation gates | `make context-validate && git diff --check -- docs && npm --prefix ../noticiencias run check:doc-drift` | context index, Markdown whitespace, and frontend cross-repo references pass |

## Scope

**In scope**: discovery interviews or operator walkthrough, correction lifecycle/identity/event contract, privacy and abuse analysis, synthetic fixtures, a local non-production state-machine prototype, visible correction-note proposal, success metrics, effort estimate, and build/no-build ADR.

**Out of scope**: a production admin UI, public issue tracker, real reporter PII in fixtures/logs, automatic factual edits, automatic refunds/rewards, outbound email integration, changing published content, or bypassing editorial approval.

## Git workflow

- Branch: `advisor/047-correction-loop-spike` in both repositories only if cross-repo fixtures are required.
- Commit example: `docs: evaluate reader correction loop`.
- Keep the spike artifact and synthetic prototype clearly labeled non-production.

## Steps

### Step 1: Establish the problem and operator

Identify who receives reports after plan 023, current volume/quality if safely available, how corrections are made today, acceptable response expectations, and who may close/reject a report. Define success as improved correctness/accountability, not report count alone.

**Verify**: `docs/spikes/reader-correction-loop.md` records owner, current workflow, top failure modes, baseline availability, and explicit unanswered questions without copying reporter PII.

### Step 2: Define stable identity and lifecycle

Design a versioned report/correction envelope containing opaque report ID, normalized public URL, resolved `refinery_id`/canonical slug, content revision/hash, type, bounded description/evidence references, consent/contact separation, timestamps, and idempotency key. Define allowed transitions such as `received -> triaged -> duplicate|rejected|accepted -> correction_proposed -> correction_published -> closed`, actors, reasons, and append-only events.

**Verify**: tests reject impossible transitions, identity mismatch, stale revision edits, duplicate intake, missing decision reason, and closure before a correlated publish event.

### Step 3: Threat-model abuse and privacy

Cover spam/flooding, malicious evidence links, HTML/log injection, forged article identity, reporter harassment, sensitive-health claims, PII access, deletion requests, queue enumeration, and insider state changes. Define data minimization, retention/deletion, access/audit, rate-limit/CAPTCHA escalation, evidence fetching policy, and notification consent.

**Verify**: each retained field has purpose, access role, retention, redaction/logging behavior, and deletion treatment; remote evidence is never fetched by the prototype.

### Step 4: Prototype the cross-repo contract locally

Using only synthetic fixtures, implement a small pure state-machine/serializer and resolver that maps a canonical Noticiencias URL/revision to stable publication identity and emits a proposed correction event. Model how an approved correction PR carries the report/correction ID and how plan 021's publish callback closes the loop. Keep storage in temporary test files/memory.

**Verify**: replaying events is deterministic/idempotent; 30+ fixtures cover current, moved, corrected, deleted, unknown, duplicate, rejected, and concurrent reports; no network or production storage is touched.

### Step 5: Design the reader-visible correction record

Specify a minimal article correction note/ledger: what changed, when, why, affected revision, source/evidence policy, and whether the reporter is named only with explicit consent. Preserve historical accountability without exposing internal/PII details. Test accessibility, SEO impact, and old-link behavior as a wire-level/HTML fixture, not a production component.

**Verify**: operator and editorial review approve the information boundary; screen-reader text and schema/canonical behavior are documented.

### Step 6: Make the build/no-build decision

Compare at least: current inbox handling, a lightweight issue/queue integration, and a first-party workflow. Score time-to-triage, identity-match rate, duplicate rate, correction cycle time, auditability, privacy risk, operator load, ongoing cost, and dependency/recovery burden. Recommend the smallest option meeting the need, with staged rollout and rollback if `build`.

**Verify**: ADR states `build`, `integrate`, or `do not build`, named owner, evidence, thresholds, estimated work, dependencies, and review date. No ambiguous “explore later” outcome remains.

## Test plan

- Synthetic contract/state-transition and idempotency fixtures.
- Identity resolution for canonical, redirected, stale, deleted, and unknown URLs.
- Privacy/redaction snapshots ensuring contact/evidence data never enters public correction artifacts.
- Report form/Worker regression after prerequisite plan 023.

## Done criteria

- [ ] The workflow has a named operator, measurable objective, and versioned lifecycle contract.
- [ ] Stable publication identity and correction/publish correlation are proven locally.
- [ ] Privacy, abuse, retention, and visible-ledger boundaries are approved.
- [ ] A comparative build/integrate/no-build ADR is complete.
- [ ] No production endpoint, queue, content, or real reporter record changed during the spike.

## STOP conditions

- Stop at `do not build` if there is no accountable triage owner or report volume/impact does not justify a workflow.
- Stop if plans 021/023 have not established truthful publication/report delivery contracts.
- Stop before retaining reporter contact or sensitive evidence without an approved privacy/retention owner and deletion process.

## Maintenance notes

If approved, split implementation into intake, operator queue, correction publication, and notification plans with independent rollback. Review metrics and retention quarterly; never let automation make factual correction decisions.
