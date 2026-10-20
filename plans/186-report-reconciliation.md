# Plan 186: Reader reports — idempotent Worker intake reconciliation (060 Phase 10, item 3)

> Execute; run every verification; stop on STOP.
> **Drift check**: `git diff --stat f6f03749..HEAD -- news_collector/infrastructure news_collector/logic/workflows news_collector/storage news_collector/contracts scripts tests .env.example`

## Status

- **Priority**: P2 (060 Phase 10)
- **Effort**: M
- **Risk**: MEDIUM (new network client; idempotency guarantees)
- **Depends on**: plan 185 (contract/tables/identity resolver — merged in `51d01787`)
- **Category**: backend ingestion / reconciliation
- **Planned at**: backend `f6f03749`, frontend `8be56b31`, 2026-10-20

## Why this matters

Worker reports are now durable R2 objects (`reports/YYYY-MM-DD/<uuid>.json`, bucket
`noticiencias-reports`) and the backend has tables + identity resolution (185),
but nothing turns the intake into backend records. This slice makes the
backend pull R2 objects **idempotently** — the same object reconciled any
number of times never duplicates.

## Current state (verified anchors)

- Worker record (frontend repo `workers/src/handlers/report.ts`, read-only):
  `id` (uuid4), `submitted_at` (ISO), `environment`, `user_agent`,
  `problem_type`, `article_url?`, `description?`, `content_snippet?`,
  `evidence_url?`, `tech_browser?`, `tech_os?`, `reporter_email?`.
  Stored pretty-printed via `JSON.stringify(record, null, 2)`.
- Tables (merged 185): `ReaderReport` (`models.py:1074+`; `idempotency_key`
  unique, `status`/`resolution_status`, `resolved_refinery_id`,
  `resolved_content_sha256`, `contact_purged_at`), `ReaderReportContact`
  (email **only** here), `ReaderReportDecision`; migration `e7f1a2b3c4d5`
  (down_revision `c6d1a4e8f203`).
- Contract: `news_collector/contracts/reader_reports.py` — `ReaderReportPayload`
  mirrors the Worker validation.
- Identity: `resolve_report_identity(url, db)` +
  `normalize_published_url` in `news_collector/logic/workflows/reader_reports.py`
  (typed resolved/unresolved/ambiguous).
- Infra: **no existing R2/Cloudflare client** and no boto3 in
  `requirements.lock`; `RobustRequestsClient` lives at
  `news_collector/infrastructure/requests_client.py:140` (SSRF-safe session,
  retries, redacted headers). Env precedent for Cloudflare tokens:
  `.env.example:64` (`CLOUDFLARE_AI_API_KEY`).
- Repository precedents: `storage/article_repository.py` (cursor/page dataclasses),
  CLI precedent: `scripts/run_collector.py` (argparse + sys.path bootstrap).

## Scope

**In scope**:
- `news_collector/infrastructure/r2_client.py` — Cloudflare-REST R2 reader
- `news_collector/logic/workflows/report_reconciliation.py` — pure orchestration
- `news_collector/storage/reader_report_repository.py` — idempotent upserts
- `scripts/reconcile_reader_reports.py` — operator entrypoint
- `.env.example` additions
- tests for all of the above (no network)

**Out of scope**: decisions transitions/admin endpoints, contact purge
service, Worker/frontend changes, CI/cron/dag automation, `config.toml`
schema changes (env-only vars).

## Design

1. **R2 client** (`infrastructure/`): thin reader over `RobustRequestsClient`:
   - `list_report_keys(*, prefix="reports/", limit, cursor=None) -> page`
     with `(keys, next_cursor)` — Cloudflare `GET /accounts/{account_id}/r2/buckets/{bucket}/objects?cursor&per_page`.
   - `get_object(key) -> bytes` via `GET .../objects/{key}` (200 body; 404 →
     typed `R2ObjectMissing`).
   - Env: `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_R2_API_TOKEN`
     (Workers R2 Storage Edit), `CLOUDFLARE_R2_REPORT_BUCKET`
     (default `noticiencias-reports`). Bearer header; missing creds → typed
     error **before** any I/O.
2. **Record interpretation** (pure, `logic/workflows/report_reconciliation.py`):
   parse JSON → build `ReaderReportPayload` `model_validate` (uppercase keys are
   not accepted; too-long/invalid URL/email → **invalid with reason**, never
   dropped silently). Idempotency key = the **Worker record `id` (UUID)** —
   retries of the same payload are KV-deduped by the Worker, so the UUID is
   unique per report; a checksum of the parsed payload is stored in the
   resolution string? NO — keep it simple: dedupe only on `idempotency_key`.
3. **Repository** (`storage/reader_report_repository.py`):
   `upsert_reader_report(session, payload, submitted_at, identity, reporter_email)`
   — SELECT by `idempotency_key`; if it exists return `(existing, False)`
   without rewriting history (keep first-seen resolution; skip update); else
   insert report (+ contact row when email present) and return `(report, True)`.
   `submitted_at` = parsed `record.submitted_at`; `created_at` remains the DB
   timestamp (reconciliation time) while `submitted_at` goes on the row — use
   the existing nullable timestamp column or a JSON `payload_meta` if missing;
   **do not add columns** unless one already fits (if none fits, adapt the
   migration from 185 into a NEW Alembic revision on top of `e7f1a2b3c4d5`).
4. **Orchestrator**: for each object: fetch bytes → interpret → resolve →
   upsert → outcome. Returns a typed summary dataclass
   (`created`, `duplicates`, `invalid` with per-key reasons, `intake` counts).
   Never raises on per-object failures; errors are outcomes.
5. **Script** `scripts/reconcile_reader_reports.py`: `--limit` (default 100),
   `--since`/`--prefix`, `--dry-run` (no session writes; exit 0), violation of
   missing creds → exit 2 with a clear message; prints the JSON summary.
6. **`.env.example`**: commented entries + one-line instructions (R2 token
   requires Workers R2 Storage Edit for the account).
7. **Tests** (no real network):
   - reconciliation: valid record (all fields), minimal record, unknown
     problem_type, invalid JSON, missing URL fields → typed outcomes;
     unicode/ Guest boundary lengths; identity stamped (`resolved`/`unresolved`
     reasons preserved).
   - idempotency: reconcile the same record twice → second run counts as
     duplicate, no column changes, still exactly one contact row.
   - repository: contact row created/absent correctly; email never lands on
     the report row; FK cascade still holds.
   - r2_cclient: URL unecoding of keys, 404 → typed error, cursor propagation,
     header redaction (token never logged).
   - script: dry-run writes nothing.

## Done criteria

- [ ] Pulling the same R2 report N times yields exactly one `reader_reports`
      row (and one contact row); duplicates are counted, not silently dropped
- [ ] Identity from 185 is stamped on inserts after the row is created
- [ ] No secret value can appear in logs (token redacted end to end)
- [ ] No new pip dependency; endpoints/paths/behavior match this plan
- [ ] Gates: `make lint`, `make type` (committed), `make test`,
      `make test-contracts`, `make test-boundaries`, `make docs-check`,
      `make inventory-refresh && make inventory-check`,
      `make plans-ledger-check`

## STOP conditions

- The Cloudflare REST object endpoints require account-level permissions the
  operator token cannot hold (probe once; report).
- The record JSON shape changed (new/renamed fields) → report; do not parse
  upward-compat hacks into the pipeline.
- Storing `submitted_at` needs a schema change beyond one clear column → STOP
  (propose it, wait).
- Something in the merge/dev tiers diverges from this plan → STOP.
