# Plan 021 TODO

## Step 0: refinery_id identity fix (not an original plan step — required by its own STOP condition)
- [x] Recon: confirm refinery_id is genuinely optional/not guaranteed (contracts, ai_editor.py, refinery_engine.py)
- [x] Add `_resolve_article_identity()` in `refinery_engine.py` (id-first, title fallback with a warning log instead of silent degradation)
- [x] Verify no regressions: 44 refinery-adjacent tests + full suite match the 13-failure pre-existing baseline exactly

## Step 1: Stable publication-attempt identity
- [x] Schema: `publication_ids` field on `FrontendWebhookEvent` (done before this session, commit 3dbab75)
- [ ] Reject empty `publication_ids` at the mutation/handler level (webhook_handler.py), not the model validator
- [ ] Persist the resolved identity into `article_metadata["publication"]["refinery_id"]` via `mark_article_publishing`/`mark_article_published`

## Step 2: Preserve the publication state machine
- [ ] **First**: fix the `main.py:245` dedup hazard (move off `is_article_published`'s published_url/published_at check onto a `processing_status`-based check) — see plans/021/spec.md "Known hazard"
- [ ] Reconcile `admin_panel.py:704`/`:2420` `is_article_published`/`published_ids_in` call sites for the new meaning
- [ ] Stop `mark_article_published` from setting `processing_status="completed"` at PR-creation time; keep "publishing" + metadata `state="PR_CREATED"`
- [ ] Add repository methods to transition only named publication_ids (e.g. `reject_publication_attempts`, `complete_publication_attempts`)
- [ ] Rewire `webhook_handler.py` to match on persisted refinery_id from `publication_ids`, not branch equality
- [ ] Verify idempotent replay (already-completed/rejected articles don't get re-touched by a replayed callback)

## Step 3: Frontend envelope construction (noticiencias repo, NOT this repo)
- [ ] Fix `backend-notify.js`'s wrap-as-diagnostics-array bug
- [ ] Fix `post-publish-callback.js`'s double-envelope bug (own envelope construction directly, don't nest through backend-notify.js's diagnostics wrapping)
- [ ] Derive changed posts from real base/head SHA ranges; parse their `refinery_id` frontmatter into `publication_ids`
- [ ] Add success-path notification to `content-guard.yml` (today only `if: failure()` calls backend-notify.js at all)

## Step 4: Authentication
- [ ] Backend: fail-closed startup check when a non-loopback/public serving mode lacks `WEBHOOK_API_KEY` (needs an environment-tier concept that doesn't exist yet — design it)
- [ ] Frontend: add `Authorization: Bearer` header to `backend-notify.js` using a new `BACKEND_WEBHOOK_TOKEN` secret
- [ ] Operator action (flag, don't attempt): set the actual `BACKEND_WEBHOOK_TOKEN` GitHub Actions secret and matching backend `WEBHOOK_API_KEY` env value

## Step 5: Cross-repo contract test
- [ ] Local capture-server test: real frontend envelope → backend Pydantic validation → real handler → real DB state transition, without network

## Constraint reminder
Steps 1(handler)+2+3 must land together (see spec.md "the coupling that
blocks a clean single-session finish") — landing backend-only makes real
callbacks stop transitioning articles at all. Don't ship one without the
other two.
