# Plan 021 TODO

Full narrative: `plans/021/spec.md`. Status: Steps 0-3 and 5 DONE, Step 4
code DONE (real secret values are the operator's own action).

## Step 0: refinery_id identity fix (not an original plan step — required by its own STOP condition) — DONE
- [x] Recon: confirm refinery_id is genuinely optional/not guaranteed (contracts, ai_editor.py, refinery_engine.py)
- [x] Add `_resolve_article_identity()` in `refinery_engine.py` (id-first, title fallback with a warning log instead of silent degradation)
- [x] Verify no regressions: 44 refinery-adjacent tests + full suite match the 13-failure pre-existing baseline exactly

## Step 1: Stable publication-attempt identity — DONE
- [x] Schema: `publication_ids` field on `FrontendWebhookEvent` (done before this session, commit 3dbab75)
- [x] Reject empty `publication_ids` at the handler level (`webhook_handler.py` logs and no-ops rather than mutating anything; the model-level `test_publication_ids_empty_list_accepted` test for non-mutation events is untouched and still passes)
- [x] Persist the resolved identity into `article_metadata["publication"]["refinery_id"]` via `mark_article_published` (confirmed identical to the frontmatter value `_resolve_article_identity` writes, by construction)

## Step 2: Preserve the publication state machine — DONE
- [x] **First**: fixed the `main.py:245` dedup hazard — new `is_article_in_flight_or_done`/`articles_in_flight_or_done` (processing_status-based), not `is_article_published`'s published_url/published_at check
- [x] Reconciled `admin_panel.py`'s two `is_article_published`/`published_ids_in` call sites to the new method, preserving their existing observable behavior (technically out of this plan's file scope, but leaving them broken would have been a silent regression)
- [x] `mark_article_published` no longer sets `processing_status="completed"` at PR-creation time; keeps `"publishing"` + metadata `state="PR_CREATED"` (reused the existing, previously-orphaned `frontend_checks` scaffold rather than rebuilding it)
- [x] Added `reject_publication_attempts(refinery_ids, reason)` / `complete_publication_attempts(refinery_ids, deploy_url)` — transition only named, still-`"publishing"` rows; idempotent by construction
- [x] Rewired `webhook_handler.py` to match on persisted `refinery_id` from `publication_ids`, not branch equality
- [x] Verified idempotent replay (a completed attempt replayed again is a no-op — covered in both the unit tests and the Step 5 cross-repo test)
- [x] Found and fixed an additional hazard not previously documented: `get_publishing_state` now returns `None` once a PR exists (not just once `processing_status != "publishing"`), preventing `attempt_recovery` from creating a duplicate PR after `PUBLISHING_TIMEOUT_SECONDS` on an article that's just slow, not stuck

## Step 3: Frontend envelope construction (noticiencias repo) — DONE
- [x] Fixed `backend-notify.js`'s wrap-as-diagnostics-array bug at the root: refactored into exported `buildEnvelope()`/`sendWebhookNotification()` functions plus a thin CLI wrapper
- [x] Fixed `post-publish-callback.js`'s double-envelope bug by calling those exports directly in-process instead of writing a file and spawning a subprocess — makes the bug class structurally impossible, not just patched
- [x] New `scripts/utils/publication-ids.js`: derives changed posts from real base/head SHA ranges (`git diff --diff-filter=ACM`), parses their `refinery_id` frontmatter via `gray-matter`
- [x] `content-guard.yml`'s failure path now derives and sends `publication_ids` too (both workflows' checkouts switched to `fetch-depth: 0` for this)
- [x] Did NOT add a new Content-Guard success-path notification — `process_validation_result` is already a no-op on `status != "fail"`, so there was nothing for a success callback to do; not scope creep to add one

## Step 4: Authentication — code DONE, secrets pending the operator
- [x] Backend: `verify_webhook_token` fails closed (503) when `WEBHOOK_API_KEY` is unset and `get_runtime_config().environment != "development"` — reused the existing environment-tier concept rather than inventing one
- [x] Frontend: `sendWebhookNotification` adds `Authorization: Bearer $BACKEND_WEBHOOK_TOKEN` when set; never logs the token (dedicated test)
- [x] `deploy.yml`/`content-guard.yml` reference `secrets.BACKEND_WEBHOOK_TOKEN` (IDE flags "context access might be invalid" — expected, the secret doesn't exist yet)
- [ ] **Operator action (not attempted, per the standing constraint)**: create the actual `BACKEND_WEBHOOK_TOKEN` GitHub Actions secret and the matching backend `WEBHOOK_API_KEY` deployment env value, and set the backend's `environment` config to something other than `"development"` wherever it's actually deployed

## Step 5: Cross-repo contract test — DONE
- [x] `tests/integration/test_publication_callback_contract.py`: real frontend `buildEnvelope()` (via a one-line Node subprocess reading the sibling repo's actual file) → real backend Pydantic validation → real handler → real SQLite DB state transition — no network anywhere
- [x] Covers all six named cases: PR/Content-Guard failure, deploy success, replay, unrelated id, auth enabled (valid + missing token), malformed envelope (×2)
- [x] Skips gracefully (not silently, not by failing) when Node or the sibling repo isn't present

## Verify (final)
- [x] Backend: `pytest tests --ignore=tests/e2e_pipeline` → same 13 pre-existing failures (confirmed via git-stash diffing), 1275 passed (+13 net new). `black`/`ruff` clean; `mypy` — same 14 pre-existing errors, zero new.
- [x] Frontend: `npm run test:audit` → 38/38 files, 220/220 tests. `astro check`/`prettier`/`eslint` clean.

## What's genuinely still open
- [ ] Operator sets the real secret values (see Step 4 above).
- [ ] No live end-to-end run yet exists (nothing to round-trip against — no production deployment per plan 046).
