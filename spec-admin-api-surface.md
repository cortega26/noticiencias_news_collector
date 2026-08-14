# Spec: Admin API surface (Phase 1 — Refinery GUI decoupling)

## Goals

Give the Refinery GUI a typed, authenticated, read-oriented HTTP surface it can
consume instead of reaching into the backend in-process. This is Phase 1 of the
Refinery revamp: **the API contract comes first, the GUI framework decision
(Streamlit revamp vs. migration) is downstream and out of scope here.**

Success criteria:

1. Every data need the current `apps/refinery/admin_panel.py` satisfies by
   direct `DatabaseManager` / raw SQL / file reads is available as a typed,
   authenticated HTTP endpoint.
2. Governance-compliant: `serving/` stays read-oriented (LAW-B4 exception:
   read-only query composition against storage models is allowed). No editorial
   state mutation happens "through convenience endpoints" (§3.6) — the two
   mutation endpoints dispatch to existing storage/workflow transitions
   (idempotent, refinery_id-keyed), mirroring the webhook precedent.
3. Auth fails closed outside the `development` environment tier, reusing the
   exact `verify_webhook_token` constant-time pattern with a distinct
   `ADMIN_API_KEY` credential (never shared with the frontend CI webhook).
4. Deterministic pagination everywhere (LAW-B10), reusing the plan-045
   explicit-projection + cursor pattern already proven in `/v1/articles`.

## Implementation details

### New contract module: `news_collector/contracts/admin.py`

Typed Pydantic shapes (LAW-B1) mirroring the plan-045 projection style:

- `AdminArticleListItem` — id, title, summary, url, source{id,name}, category,
  topics, published_at, collected_at, final_score, score_components,
  why_ranked, processing_status, error_message, published_url, refinery_id
  (from `article_metadata["publication"]["refinery_id"]`).
- `AdminArticleListEnvelope` — data[], pagination{next_cursor,has_more,
  page_size,returned}, filters{status,source}, meta{generated_at}.
- `AdminArticleDetail` — everything from the list item plus content,
  article_metadata, cluster_id, publishing state snapshot
  (`article_metadata["publication"]`), audit state
  (`article_metadata["audit"]`), and latest `ScoreLog` row.
- `AdminSourceHealthRecord` — reuse `SourceHealthRecord` from
  `news_collector/contracts/source_health.py` (no new shape; the collector
  export is `data/exports/source_health.json`).
- `AdminAnalyticsEnvelope` — the `build_analytics_read_model` dict plus
  `as_of` timestamp.
- `AdminConfigSnapshot` — sanitized read of `config.toml`: only the
  non-secret, GUI-relevant keys (sources list, scoring weights, model names,
  GitHub target repo URL). Explicit allowlist; never tokens/keys.
- `AdminAuditStatusUpdate` — `audit_status` (str), optional `reason` (str).
- `AdminRejectRequest` — optional `reason` (str).
- `AdminMutationResult` — `status` (ok|not_found|noop), `detail`, `updated`.

### New auth dependency: `verify_admin_token` (in `serving/api.py`)

Identical constant-time Bearer check as `verify_webhook_token`, but:

- Reads `ADMIN_API_KEY` env var (never `WEBHOOK_API_KEY`).
- Fails closed (`503`) outside `development` when the key is unset.
- `401` missing header / malformed scheme, `403` wrong key — same codes.

### New endpoints (all under `/v1/admin`, all `Depends(verify_admin_token)`)

| Endpoint | Method | Purpose | Backend source |
|---|---|---|---|
| `/v1/admin/articles` | GET | Triage queue: status-filtered, cursor-paginated, score components + why_ranked | `ArticleRepository.get_articles_by_score`-style query with `processing_status` filter + plan-045 projection |
| `/v1/admin/articles/{id}` | GET | Full article detail incl. latest ScoreLog + publication/audit state | `ArticleRepository.get_article_by_id` + ScoreLog latest |
| `/v1/admin/sources/health` | GET | Source health records | Read `data/exports/source_health.json` (same artifact `load_source_health()` reads) |
| `/v1/admin/analytics` | GET | Analytics read model | `AnalyticsRepository` + `build_analytics_read_model` + `as_of` |
| `/v1/admin/config` | GET | Sanitized config snapshot | `load_config()` + explicit allowlist |
| `/v1/admin/articles/{id}/audit-status` | POST | Record auditor outcome (metadata only) | dispatch → `DatabaseManager.update_article_audit_status` (existing, idempotent) |
| `/v1/admin/articles/{id}/reject` | POST | Reject named in-flight publication attempts | dispatch → `ArticleRepository.reject_publication_attempts` (existing, idempotent, refinery_id-keyed) |

**Explicitly out of scope (documented, not built):**

- Approve/publish workflows (they create PRs and run the engine — that is a
  workflow concern, not a serving concern; the Refinery keeps calling them
  in-process for now).
- Reprocess (engine run) — same reason.
- Config writes, secrets writes, git operations.
- The GUI itself (Streamlit revamp or migration) — Phase 2 decision.

### Files to change

1. `news_collector/contracts/admin.py` — **new** typed models.
2. `news_collector/serving/api.py` — `verify_admin_token` + 7 endpoints.
3. `news_collector/serving/__init__.py` — no change needed (`create_app` export).
4. `tests/test_serving_admin_api.py` — **new** test module (see Verification).
5. `docs/PIPELINE_CONTRACTS.md` — add the admin surface to the serving-layer
   contract inventory (docs follow code, §9).
6. `.env.example` — document `ADMIN_API_KEY` next to `WEBHOOK_API_KEY`.

## Verification

Prove each piece with `tests/test_serving_admin_api.py` (pytest, `e2e`
marker, TestClient over a tmp sqlite DB — same fixture style as
`tests/test_serving_api.py`):

1. **Auth fail-closed**: no `ADMIN_API_KEY` + non-development runtime →
   `503`; missing header → `401`; wrong key → `403`; correct key →
   `200/4xx-not-401`. (Env override via monkeypatch + runtime config patch.)
2. **Triage list**: seeded articles with mixed `processing_status`
   (pending/completed/rejected) → status filter returns only matching rows;
   payload carries score_components, why_ranked, refinery_id; pagination
   cursor traversal has no gaps/duplicates and terminates.
3. **Detail**: returns content + latest ScoreLog + publication/audit state;
   unknown id → `404`.
4. **Source health**: seeded export file → parsed records; missing file →
   empty envelope (200, not 500).
5. **Analytics**: seeded DB → read model fields present (`total_articles`,
   `stats`, `source_perf`, `avg_score_overall`); `as_of` is recent ISO.
6. **Config**: returns allowlisted keys only; a planted secret key
   (e.g. `github.token`) is absent from the payload.
7. **Mutations**: audit-status update persists to `article_metadata["audit"]`
   and is idempotent; reject transitions named publishing attempts to
   `rejected` and returns `noop` for already-rejected ids.

### Validation commands

```bash
make lint
make type
make test-contracts          # contract/boundary change
make test-boundaries         # serving change
pytest tests/test_serving_admin_api.py -q
make test                    # full unit suite (0-warning check)
```

Change class: Contract/adapter/boundary + serving → **High** risk (matrix §10):
baseline + `test-contracts` + `test-boundaries` + targeted tests.

## Risks / mitigations

- **Serving must not mutate editorial state** — mitigated by dispatching only
  to existing idempotent storage transitions (audit-status, reject-by-refinery_id),
  the same pattern the webhook handler already uses.
- **Secret leakage in `/v1/admin/config`** — mitigated by an explicit
  allowlist and a test asserting a planted secret is absent.
- **Pagination determinism** — reuses the plan-045 cursor format; a
  traversal test asserts no gaps/duplicates.
- **Streamlit coupling** — none introduced: this module imports only
  `serving/`, `contracts/`, `storage/`; no `streamlit` import (the test venv
  has no streamlit, same constraint as plan 038 read model).
