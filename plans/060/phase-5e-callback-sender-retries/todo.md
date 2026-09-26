# Plan 060 / Phase 5e todo — Callback sender delivery IDs, bounded retries, diagnostics

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this
checklist alone. All work happens in `../noticiencias`.

## Step 0 — baseline + drift

- [x] Drift check clean at frontend `13fae76` (branch created; diff empty).
- [x] `npm run test:audit` baseline recorded (780 passed).

## Step 1 — sender implementation + tests

- [x] `buildEnvelope` emits `delivery_id` = `v1:<run_id>:<event>` when a run
      id exists; omitted otherwise (tests cover presence, absence, stability,
      per-event distinctness).
- [x] `sendWebhookNotification` bounded retries (3 attempts, 1 s/2 s),
      retrying only network/429/5xx; returns `attempts`; env overrides.
- [x] final failure writes the diagnostic artifact; success writes none.
- [x] `post-publish-callback.js` passes the artifact path and logs attempts.
- [x] tests extended to 21 (delivery id, retry matrix, artifact, env bound,
      no token in logs).

## Step 2 — workflows

- [x] artifact upload step in the six caller workflows (content-guard,
      deploy, generate-metrics, image-delivery-quota, sync-contract-snapshot,
      bot-health; pinned `upload-artifact` v4.6.2).
- [x] `bot-health.yml` checks `https://api.noticiencias.com/readyz`
      (scheduled-workflow failure email is the alert channel).

## Step 3 — gates + docs

- [x] `npm run lint` + `npm run validate:content` + `npm run test:audit`
      (790 passed) green; workflow YAML parses.
- [x] `plans/060/todo.md` Phase 5 item 1 checked with evidence.
- [x] `scripts/validate_plans_ledger.py` OK (backend repo).
- Frontend PR: `noticiencias#226`.
