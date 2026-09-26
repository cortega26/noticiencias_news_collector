# Plan 060 / Phase 5e — Callback sender delivery IDs, bounded retries, diagnostics

> **Executor instructions**: This phase edits the **frontend repository**
> (`../noticiencias`); the plan artifacts live here. Follow the spec step by
> step, run every verification command in the frontend repo, and confirm the
> expected result before moving on. When done, annotate `plans/060/todo.md`
> Phase 5 item 1 and validate the plans ledger.
>
> **Drift check (run first, in `../noticiencias`)**:
> `git diff --stat <frontend-head>..HEAD -- scripts/backend-notify.js scripts/post-publish-callback.js tests/backend-notify.test.ts .github/workflows/bot-health.yml .github/workflows/content-guard.yml .github/workflows/deploy.yml .github/workflows/generate-metrics.yml .github/workflows/image-delivery-quota.yml .github/workflows/sync-contract-snapshot.yml`
> On any in-scope drift, re-verify the "Current state" references; on a
> mismatch treat it as a STOP.

## Status

- **Priority**: P1
- **Effort**: S/M
- **Risk**: LOW (best-effort sender; deploy stays non-blocking)
- **Depends on**: Phase 5a (backend accepts optional `delivery_id` and
  dedupes derived keys). Closes the last open Phase 5 item.
- **Category**: reliability (plan 060 Phase 5 item 1)
- **Planned at**: frontend `13fae76`, backend `539372c`, 2026-09-26

## Why this phase exists

Plan 060 Phase 5 item 1:

> Add a versioned delivery/idempotency ID to callback envelopes. Frontend sends
> bounded retries with exponential backoff and emits a diagnostic artifact on
> failure; deployment stays non-blocking.

The backend half landed in 5a (optional `delivery_id`; a stable derived key
when absent). The sender still posts once, has no retry, and leaves no
diagnostic record when a delivery is lost. After the OCI migration the
backend is a single host behind one tunnel connector, so a transient network
blip or a restart window is exactly the case bounded retries cover.

## Current state (verified at frontend `13fae76`)

- `scripts/backend-notify.js:56` `buildEnvelope` — no `delivery_id` field;
  `sendWebhookNotification:87` posts once, never throws, returns
  `{ok,status}`/`{error}`.
- `scripts/post-publish-callback.js` — imports both functions; prints a
  warning on failure, exits 0 (deploy stays non-blocking).
- Callers: `content-guard.yml:111` (validation fail), `deploy.yml:149`
  (publish complete), `generate-metrics.yml:65`, `image-delivery-quota.yml:94`,
  `sync-contract-snapshot.yml:58`, `bot-health.yml:64` — all `|| true`.
- `tests/backend-notify.test.ts` — 11 tests; no retry/delivery-id coverage.
- `bot-health.yml` checks bot workflow freshness but **not** backend
  readiness.
- Backend contract: `delivery_id` optional, ≤128 chars, non-blank
  (`contracts/webhook.py`); `compute_delivery_key` uses `id:<delivery_id>`.

## Scope

**In scope** (all in `../noticiencias`):

- `scripts/backend-notify.js`:
  - `buildEnvelope` adds `delivery_id: "v1:<GITHUB_RUN_ID>:<event>"` when a
    real run id exists (omitted otherwise so the backend derives its stable
    key; never fabricate a shared id across runs).
  - `sendWebhookNotification` bounded retries with exponential backoff:
    default 3 attempts, delays 1 s then 2 s, retrying only on network errors,
    429 and 5xx (never on other 4xx — deterministic failures are not
    retried); returns `attempts` in the result; still never throws.
    `maxAttempts`/`baseDelayMs`/`sleepImpl`/`failureArtifactPath` injectable
    for tests; env overrides `BACKEND_WEBHOOK_MAX_ATTEMPTS`,
    `BACKEND_WEBHOOK_RETRY_BASE_MS`.
  - On final failure, writes a bounded JSON diagnostic artifact
    (`event`, `delivery_id`, `run_url`, `attempts`, `status`/`error`,
    `generated_at`) to `failureArtifactPath`; write failures are logged, never
    raised.
- `scripts/post-publish-callback.js` — passes the artifact path
  (`RUNNER_TEMP`/`backend-notify-failure.json` fallback) and logs attempts.
- Workflows that invoke either sender — add an `actions/upload-artifact`
  step (`if: always()`, `if-no-files-found: ignore`, name
  `backend-notify-failure`) so a lost delivery leaves a CI-visible artifact.
- `bot-health.yml` — also check `https://api.noticiencias.com/readyz`
  (failure exits non-zero → GitHub's own scheduled-failure notification is
  the alert channel, independent of the backend being down).
- `tests/backend-notify.test.ts` — delivery-id stability, retry matrix
  (5xx retried, 4xx not, exhausted attempts), artifact written only on final
  failure, no token in logs.

**Out of scope**:

- Backend changes (5a already accepts/dedupes).
- Queueing/durable sender-side storage beyond the diagnostic artifact.
- Retry policy for other notification consumers (none exist).
- Changing deploy/CI blocking semantics: senders stay best-effort and exit 0.

## Design

`delivery_id` = `v1:<run_id>:<event>` — stable across retries of the same
workflow run+event, distinct across runs, ≤128 chars. Local runs without
`GITHUB_RUN_ID` omit the field and the backend derives its key.

Retry matrix:

| outcome | retry? |
|---|---|
| network error / timeout | yes |
| HTTP 429 | yes |
| HTTP 5xx | yes |
| HTTP 4xx (other) | no |
| 2xx | done |

Backoff: `baseDelayMs * 2^(attempt-1)` (1 s, 2 s by default), no jitter so
tests and logs are deterministic. Worst case added latency ~3 s, bounded for
CI; the script still exits 0.

## Test plan

- Envelope: `delivery_id` present with `GITHUB_RUN_ID`, absent without it,
  stable across repeated builds, format/version prefix.
- Sender: 500 then 202 → 3 calls, `attempts: 3`, slept twice; 400 → 1 call,
  no sleep; all-500 → `ok: false`, `attempts: 3`, artifact file exists with
  expected keys; success → no artifact; injected `sleepImpl` keeps tests
  fast; token never logged.
- Existing assertions that assumed a single attempt are updated to the new
  contract (retries are the feature; behavior for deterministic 4xx is
  unchanged).
- Frontend gates: `npm run lint`, `npm run test:audit`, and the workflow YAML
  stays valid (`actionlint` if available; otherwise `python -c yaml.safe_load`).

## Steps

### Step 0: Baseline + drift

Record `npm run test:audit` count; STOP on drift/non-green.

### Step 1: Sender implementation + tests

`buildEnvelope` delivery id; retry/backoff/artifact in
`sendWebhookNotification`; update `post-publish-callback.js`; extend tests.

### Step 2: Workflows

Artifact upload steps in the six caller workflows; `bot-health.yml` backend
readiness check.

### Step 3: Gates + docs

Frontend gates; annotate `plans/060/todo.md` Phase 5 item 1; ledger OK.

## Done criteria (machine-checkable)

- [ ] `delivery_id` emitted as `v1:<run_id>:<event>` and stable across
      retries; omitted when no run id (tests)
- [ ] 5xx/429/network retried up to the bound; other 4xx not retried (tests)
- [ ] Final failure writes the diagnostic artifact; success writes none
      (tests)
- [ ] Senders still never throw and exit 0 (tests + review)
- [ ] Caller workflows upload the artifact when present; bot-health checks
      backend readiness
- [ ] Frontend `npm run lint` + `npm run test:audit` green
- [ ] `plans/060/todo.md` item 1 checked; ledger OK
- [ ] Frontend diff only in-scope files

## STOP conditions

- Drift/baseline not clean in either repo.
- Any change to the envelope's existing fields, the webhook URL/token
  handling, or deploy/CI blocking semantics.
- A retry policy that could block a deploy longer than ~10 s.

## Git workflow

- Frontend branch: `advisor/060-phase-5e-callback-sender-retries` (off `main`).
- Frontend commit: `feat(ci): versioned delivery ids with bounded callback retries`.
- Do NOT push/PR unless instructed.
