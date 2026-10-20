# Plan 185: Reader reports — contract, storage and identity resolution (060 Phase 10, items 1–2)

> Execute; run every verification; stop on STOP.
> **Drift check**: `git diff --stat 09049e83..HEAD -- news_collector/contracts news_collector/storage/models.py alembic/versions news_collector/logic/workflows tests`

## Status

- **Priority**: P2 (060 Phase 10)
- **Effort**: M
- **Risk**: MEDIUM (first schema/migration of the feature)
- **Depends on**: none; foundation for the reconciliation/admin slices
- **Category**: backend data model / identity
- **Planned at**: backend `09049e83`, frontend `8be56b31`, 2026-10-20

## Why this matters

The frontend Worker accepts and validates reader reports
(`ReportPayload` in `workers/src/utils/validate.ts`: six problem types,
article URL, description, snippet, evidence URL, tech fields, optional email),
but the backend has **no reader-report/correction tables or endpoints** — only
frontmatter correction fields. Reports go nowhere traceable. Phase 10 needs a
durable record tied to the **published revision** it refers to, with contact
data separated from the report body for the privacy contract.

## Current state

- Worker contract: `problem_type` ∈ {content_factual, content_source,
  content_interpretation, content_translation, technical_site,
  technical_visual}; lengths: url 2000, description 5000, snippet 2000,
  evidence 2000, browser/os 200, email 320; `article_url` must be
  `noticiencias.com` or a subdomain (dot-boundary).
- `Article.published_url` is set from the deploy callback (`lifecycle_repository`)
  and is the canonical frontend URL; `Article.id` is the refinery id.
- `PublicationAttemptRecord` (refinery_id, article_id, details JSON) stores the
  attempt summary; the `publication_content_fingerprint` stage carries
  `content_sha256` (target_repo_publication). `Article.content_hash` is the
  source content revision fallback.
- Alembic head: `c6d1a4e8f203`. Models: `news_collector/storage/models.py`;
  contracts are pure Pydantic (`contracts/admin.py` style).

## Scope

**In scope**:
- `news_collector/contracts/reader_reports.py` — payload/identity contracts
- `news_collector/storage/models.py` — three tables
- one Alembic migration under `alembic/versions/`
- `news_collector/logic/workflows/reader_reports.py` — URL normalization +
  identity resolution (no API, no Worker fetch yet)
- tests: contract, model/migration, resolver

**Out of scope**: Worker reconciliation/fetch, admin endpoints/UI, decisions
transitions, publication/deploy evidence links, the Worker/frontend repo,
changing `Article`/publication models.

## Data model (mirror repo conventions)

- `reader_reports`: id, `idempotency_key` (unique, from the intake delivery
  key/hash), `problem_type`, `article_url`, `description`, `content_snippet`,
  `evidence_url`, `tech_browser`, `tech_os`, `status`
  (`new|triaged|accepted|rejected|duplicate|no_action`), `resolution_status`
  (`unresolved|resolved|ambiguous`), `resolved_refinery_id`,
  `resolved_content_sha256`, `resolution_reason`, `created_at`, `updated_at`,
  `contact_purged_at` (nullable).
- `reader_report_contacts`: `report_id` unique FK (cascade), `email`,
  `created_at`. Contact data lives **only here** (privacy separation).
- `reader_report_decisions`: `report_id` FK, `decision`
  (`accepted|rejected|duplicate|no_action`), `actor`, `notes`,
  `corrected_at`, `correction_summary`, `publication_ref`, `deploy_evidence`,
  `created_at`, `closed_at` (nullable).
- Indexes on idempotency_key, status, resolution_status, resolved_refinery_id,
  report_id FKs. UTC timestamps per existing models.

## Steps

1. **Contracts**: `ReaderProblemType` (Literal/enum with the six values),
   `ReaderReportPayload` (Pydantic; field lengths and URL host validation
   mirroring the Worker; email optional), `ReaderReportStatus`,
   `ReaderResolutionStatus`, `ReportIdentity` (status, canonical_url,
   refinery_id, content_sha256, reason). Pure, no I/O.
2. **Models + migration**: add the three models; generate the Alembic revision
   with `down_revision = "c6d1a4e8f203"` (use the repo's migration style and a
   deterministic revision id); ensure upgrade/downgrade work on SQLite.
3. **Identity resolver** (`logic/workflows/reader_reports.py`):
   - `normalize_published_url(url)`: http/https, lowercase scheme/host, strip
     trailing slash, drop query/fragment, keep the path; reject other hosts.
   - `resolve_report_identity(url, db) -> ReportIdentity`: match
     `Article.published_url` under the normalized variants; 0 → unresolved with
     a reason; >1 → ambiguous; 1 → `refinery_id = str(article.id)`, content
     revision from the latest `PublicationAttemptRecord.details` stage
     `publication_content_fingerprint.content_sha256` (fallback
     `article.content_hash`), canonical URL.
   - Read-only; no writes, no HTTP.
4. **Tests** (real SQLite via `DatabaseManager`):
   - contract: each problem type, length bounds, non-noticiencias host, email
     optional/limit.
   - models: round-trip, idempotency uniqueness, contact cascade, decision
     fields; migration upgrade/downgrade (follow `tests/test_database_migrations.py`
     patterns).
   - resolver: exact URL, trailing slash, query/fragment, uppercase host,
     http vs https, unresolved, ambiguous, content hash from the latest attempt
     and the `article.content_hash` fallback.
5. Gates: `make lint`, `make type` (committed), `make test`,
   `make test-contracts`, `make test-boundaries`, `make docs-check`,
   `make inventory-refresh && make inventory-check`, `make plans-ledger-check`.

## Done criteria

- [ ] Contract, tables+migration and identity resolver implemented, no API yet
- [ ] Reports can be durably stored with idempotency and separated contact data
- [ ] Identity resolves URL → refinery_id + content revision, or a typed unresolved/ambiguous reason
- [ ] Tests cover contract/model/migration/resolver; gates green
- [ ] `git diff --name-only main...HEAD` limited to the in-scope files
- [ ] Ledger row 185 updated by the reviewer

## STOP conditions

- The migration cannot round-trip on SQLite (report the DDL/constraint).
- The resolver would need a frontend/source change to identify articles
  (`published_url` is null for legacy articles) → report; unresolved is a valid
  outcome, do not guess.
- The contact separation needs encryption/key management not present in the repo
  → report; do not invent a secret store.
- Any API/reconciliation/UI is needed to test the foundation → STOP (later slices).
