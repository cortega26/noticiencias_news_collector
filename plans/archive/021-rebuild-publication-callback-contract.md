# Plan 021: Correlate and authenticate publication callbacks end to end

> **Executor instructions**: This is a coordinated two-repository change. Use separate branches if required, keep protocol changes backward-incompatible only within the same rollout, and update plan 021 in the backend `plans/README.md` when both sides are verified.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- news_collector/contracts/webhook.py news_collector/serving/api.py news_collector/serving/webhook_handler.py news_collector/storage/article_repository.py news_collector/logic/workflows/pr_orchestrator.py tests/test_webhook.py`; then in `../noticiencias`: `git diff --stat 0cdca74..HEAD -- scripts/backend-notify.js scripts/post-publish-callback.js .github/workflows/content-guard.yml .github/workflows/deploy.yml`

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plan 020
- **Category**: bug/security/tests
- **Planned at**: backend `e43bd30`, frontend `0cdca74`, 2026-07-21

## Why this matters

The current callback protocol cannot represent a real publication attempt reliably. PR creation marks the article `completed`, receivers only inspect `publishing`/`validated`, GitHub supplies PR merge or `main` refs rather than the stored publishing branch, authenticated receivers reject the sender, and the deploy script nests a complete envelope inside `diagnostics`. Validation failures and live deployments therefore do not transition the intended article.

## Current state

- `article_repository.py:185-217` stores publication metadata but sets `processing_status = "completed"` and a PR URL immediately.
- `webhook_handler.py:46-59,95-110` matches only `publishing`/`validated` articles whose `publishing_branch` equals the callback branch.
- `api.py:254-277` skips auth when `WEBHOOK_API_KEY` is absent; otherwise it requires Bearer auth.
- `contracts/webhook.py:16-39` defines diagnostic/envelope shapes but no stable publication identity.
- Frontend `backend-notify.js:81-120` wraps any JSON file as diagnostics, uses `GITHUB_REF_NAME`, and sends no Authorization header.
- `post-publish-callback.js:45-99` writes a full envelope and passes it to that diagnostics-only sender.
- Existing `tests/test_webhook.py` hand-builds idealized matching branches and begins in a state the real PR path no longer has.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend focused | `.venv/bin/python -m pytest tests/test_webhook.py tests/decompose_refinery/test_pr_orchestrator.py -q` | all pass |
| Frontend sender tests | `cd ../noticiencias && npm run test:audit -- tests/backend-notify.test.ts tests/post-publish-callback.test.ts` | all pass |
| Contract parity | `cd ../noticiencias && npm run check:contract-sync` | exit 0 |
| Full backend | `.venv/bin/python -m pytest -q` | all pass except no newly accepted baseline |

## Scope

**Backend in scope**: the five production files above, `tests/test_webhook.py`, PR orchestrator tests, and webhook docs.

**Frontend in scope**: both sender scripts, the two workflows, focused Node tests, and webhook runbook.

**Out of scope**: auto-merging PRs, changing GitHub Pages hosting, exposing the backend publicly, or adding a general event bus.

## Git workflow

- Backend branch: `advisor/021-publication-callback-contract`
- Frontend branch: `advisor/021-publication-callback-contract`
- Commit examples: `fix(publication): correlate frontend callbacks by publication id`; `fix(ci): authenticate publication callbacks`.

## Steps

### Step 1: Define a stable publication-attempt identity

Extend the webhook contract with a bounded non-empty list of `publication_ids` derived from the generated post's `refinery_id`/backend article ID. Keep `commit_sha` and branch as audit context, not the primary database key. Reject empty identity lists for publication-state mutations.

**Verify**: Pydantic tests accept valid IDs and reject missing, empty, oversized, or malformed identity lists.

### Step 2: Preserve the publication state machine

After PR creation, keep `processing_status="publishing"`; store `publication.state="PR_CREATED"`, PR URL, branch, and attempt identity. Validation failure transitions only the named attempts to `rejected`. Deployment success transitions only named validated/publishing attempts to `completed`, sets live URL/time, and never bulk-updates unrelated rows.

**Verify**: an integration test proves `publishing → PR_CREATED → validation pass/fail → deployed completed/rejected`; callbacks replay idempotently.

### Step 3: Emit exact envelopes from real GitHub event ranges

Make one sender own envelope construction. `post-publish-callback.js` must pass diagnostic records or call the envelope API directly, never feed an envelope into `diagnostics`. Derive changed post files from explicit workflow base/head SHAs and parse their `refinery_id` fields. For PR context, also use `GITHUB_HEAD_REF` for audit branch display; for deploy, use the push `before`/`sha` range.

**Verify**: Node tests with representative PR and push environment variables snapshot the exact JSON and IDs.

### Step 4: Authenticate without a fail-open production mode

Add a dedicated frontend secret (for example `BACKEND_WEBHOOK_TOKEN`) to both workflows and emit `Authorization: Bearer ...`. Backend startup must fail closed when a non-loopback/public serving mode lacks `WEBHOOK_API_KEY`; retain unauthenticated behavior only behind an explicit loopback-only development setting. Never place the token in URLs or logs.

**Verify**: absent/malformed/wrong tokens return 401/403, a valid token returns 202, and sender logs do not contain the secret.

### Step 5: Add a true cross-repo contract test

Run the Node sender against a local capture server, validate the payload with backend Pydantic models, then replay it through the real handler after the real PR-created repository transition. Cover PR failure, deploy success, replay, unrelated ID, auth enabled, and malformed envelope.

**Verify**: the new deterministic cross-repo test passes without network access.

## Test plan

- Backend contract/auth/state tests for valid, malformed, missing-ID, unrelated-ID, replayed, and out-of-order callbacks.
- Frontend sender snapshots for pull-request validation and push/deployment event ranges.
- Local capture-server test that validates the real frontend envelope with backend Pydantic models and handler state.
- Secret-redaction assertions plus full focused suites in both repositories.

## Done criteria

- [ ] No publication mutation relies on branch equality alone.
- [ ] PR creation does not mark an article live/completed.
- [ ] Both workflows send authenticated, schema-valid payloads.
- [ ] Deploy payload is not nested inside diagnostics.
- [ ] End-to-end contract/state tests pass in both repositories.
- [ ] No credential value appears in code, tests, logs, or docs.

## STOP conditions

- Stop if `refinery_id` is not present and unique for every newly generated post; report the missing producer path.
- Stop if GitHub event data cannot determine a bounded changed-post set; do not fall back to updating every pending article.
- Stop if rollout cannot coordinate frontend and backend secrets; do not enable the current unauthenticated compatibility mode.

## Maintenance notes

Treat the webhook schema as a versioned cross-repo contract. Any state or payload change must update sender snapshots, backend models, handler tests, and the operational runbook together.
