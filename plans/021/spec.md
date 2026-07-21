# Plan 021 working notes: Correlate and authenticate publication callbacks

Authoritative spec: `plans/021-rebuild-publication-callback-contract.md`. This
file records recon findings and the exact remaining work — read it before
resuming, it will save re-deriving the same investigation.

## Status: PARTIAL

Only Step 0 (a prerequisite the plan didn't originally name, but its own
STOP condition requires) is done. Steps 1–5 are coordinated cross-repo work
that cannot be split into an independently-shippable backend-only slice —
see "Why this isn't further along" below.

## What's actually in place today (recon, current as of this session)

- **Step 1 (schema) is partially done, already on `main`**: commit
  `3dbab75` added `FrontendWebhookEvent.publication_ids: List[str]` to
  `news_collector/contracts/webhook.py` (default `[]`, max 200 entries, all
  entries non-empty strings) plus 6 model-level tests in
  `tests/test_webhook.py` (search "Plan 021 Step 1"). **But it's inert**:
  no code reads `event.publication_ids` anywhere (`webhook_handler.py`
  never references it). The remaining Step 1 work — "reject empty identity
  lists for publication-state mutations" — belongs at the
  handler/mutation level, NOT the model validator (there's an existing,
  correct test `test_publication_ids_empty_list_accepted` for non-mutation
  events; don't break it).
- **Step 2 (state machine) is NOT done**: `mark_article_published()` in
  `news_collector/storage/article_repository.py:181-214` still sets
  `processing_status = "completed"` the instant a PR is opened (called
  from `pr_orchestrator.py::create_pr` on PR success). `webhook_handler.py`
  still matches only by `article_metadata["publishing_branch"] ==
  event.branch` across *all* `publishing`/`validated` rows — exactly the
  "branch equality" bug the plan describes. `publication_ids` is never
  consulted.
- **Step 3 (frontend envelope) is NOT done**: confirmed both bugs described
  in the plan are real and current in the sibling `noticiencias` repo:
  - `scripts/backend-notify.js` wraps any non-array payload-file JSON as
    `diagnostics: [thatObject]` — the literal mechanism that nests a full
    envelope inside `diagnostics`.
  - `scripts/post-publish-callback.js` builds a complete envelope, writes
    it to a file, then calls `backend-notify.js` with that file as the
    payload — producing the double-nested envelope bug.
  - Neither script emits `publication_ids`, `content-guard.yml` only calls
    `backend-notify.js` on `if: failure()` (no success-path notification
    at all today), and neither script sends an `Authorization` header.
- **Step 4 (auth) is NOT done**: `verify_webhook_token` in
  `news_collector/serving/api.py` fails OPEN when `WEBHOOK_API_KEY` is
  unset (`.env.example` explicitly documents this as intentional "dev
  mode"). No environment-tier/serving-mode concept exists to gate a
  fail-closed requirement in production. `BACKEND_WEBHOOK_TOKEN` (the
  plan's suggested frontend secret name) appears nowhere in either repo —
  it's purely a suggestion in the plan text.
- **Step 5 (cross-repo contract test) is NOT done**: no local capture
  server / cross-repo replay test exists.

## Step 0 (this session): refinery_id identity fix — DONE

The plan's STOP condition says: *"Stop if `refinery_id` is not present and
unique for every newly generated post."* Recon found it genuinely isn't
guaranteed:
- `contracts/frontend_schema.py` and the frontend's `content.config.ts`
  both mark `refinery_id` `Optional`.
- `ai_editor.py`'s frontmatter builder only sets `refinery_id` when
  `article_id and article_id != "unknown"` — a real omission path.
- The `article_id` feeding that check came from
  `refinery_engine.py`'s `str(article.get("id", article.get("title")))` —
  falling back to the **title** (not the DB id) whenever the `"id"` key was
  merely absent from the dict, silently.

**First attempt (reverted): making `article["id"]` a hard requirement was
wrong.** It broke `tests/test_refinery_contract_enforcement.py`'s
`valid_article` fixture (no `"id"` key at all, asserts
`process_single_article(...) is True`) and doesn't account for the real
filesystem-fallback ingestion path in `apps/refinery/main.py` (~line 634-641)
which uses `"id": file_path.name` — a filename, not a DB primary key. Both
are legitimate today; a hard requirement is a regression, not a fix.

**What shipped instead**: `_resolve_article_identity()` in
`refinery_engine.py` — prefers `article["id"]` when present, falls back to
title (same as historical behavior) but **logs a warning** instead of
silently degrading. Near behavior-neutral by design (see its docstring for
why); it's groundwork for Step 2, not a state-machine change. Verified: the
44 refinery/engine-adjacent tests + full `pytest tests
--ignore=tests/e2e_pipeline` still match the pre-existing 13-failure
baseline exactly (1149 passed).

## The coupling that blocks a clean single-session finish

Steps 1, 2, and 3 are one wire with two ends:
- If the backend starts rejecting empty `publication_ids` for mutations
  (Step 1) and/or switches matching to `publication_ids` (Step 2) **before**
  the frontend actually populates that field (Step 3), every real callback
  will match nothing — **articles get permanently stranded in
  `publishing`, a regression versus today's imperfect-but-working
  branch-based matching.** Landing the backend half alone and seeing green
  tests would be hollow (exactly the risk plan's own Step 5 exists to
  catch) — worse, deployed alone it actively breaks production callback
  processing.
- Step 4 (auth) has an operator-secret boundary identical to plan 001's
  credential rotation: the actual `BACKEND_WEBHOOK_TOKEN` GitHub Actions
  secret value and the backend's deployed `WEBHOOK_API_KEY` are the
  operator's to set and coordinate, not something achievable via a code
  change alone.
- Frontend work (Step 3, and the auth-sending half of Step 4) lives in the
  sibling `noticiencias` Astro repo, not here.

## Known hazard for whoever does Step 2 (found during recon, not yet fixed)

Decoupling PR-creation from `processing_status = "completed"` (required by
Step 2) will break an existing dedup guard:
`apps/refinery/main.py:245` — `if not process_id and
db_manager.is_article_published(numeric_id): continue` — skips
reprocessing articles that are already published. `is_article_published`
(`article_repository.py:262`) and `published_ids_in`
(`article_repository.py:270`) both key off `published_url`/`published_at`,
which `mark_article_published` currently sets at PR-creation time. If PR
creation stops setting those fields (correct per Step 2 — they shouldn't
mean "published" until real deploy), this dedup guard will start
re-selecting articles with an already-open, still-pending PR —
**producing duplicate PRs for the same article.**

Before touching `mark_article_published`, Step 2's implementer must:
1. Move the `main.py:245` dedup check to something `processing_status`-based
   (`in ("publishing", "completed")`, not just the published-fields check).
2. Reconcile the ~4 other `is_article_published`/`published_ids_in` call
   sites (`admin_panel.py:704`, `:2420`) — they currently mean "PR exists,
   maybe not even merged"; decide what they should mean post-Step-2 and
   whether they need a new query (e.g. `processing_status == "completed"`
   directly) instead.

## Recommended next steps (in order, when resumed)

1. Design the persisted-identity approach: store the exact string
   `_resolve_article_identity()` returns into
   `article_metadata["publication"]["refinery_id"]` via
   `mark_article_publishing`/`mark_article_published`, so Step 2's webhook
   matching queries against a persisted value rather than assuming
   `Article.id` int-castability (this handles the filename-fallback case
   cleanly too).
2. Fix the `main.py:245` dedup hazard above *before* changing
   `mark_article_published`'s `processing_status` behavior.
3. Implement Step 2's repository methods (e.g.
   `reject_publication_attempts(refinery_ids, ...)`,
   `complete_publication_attempts(refinery_ids, deploy_url)`) and rewire
   `webhook_handler.py` to use them, gated on non-empty `publication_ids`
   (closes remaining Step 1 too).
4. In the `noticiencias` frontend repo: fix the double-envelope bug, add
   `publication_ids` derivation (parse changed posts' `refinery_id`
   frontmatter from the real git diff range), add the
   `Authorization: Bearer` header — land Steps 1-2-3 together, verify with
   a real cross-repo run, not backend-tests-green alone.
5. Step 4 auth: implement fail-closed backend logic (gated on an
   environment-tier concept that doesn't exist yet — will need its own
   small design) and frontend bearer-token sending; flag the actual secret
   values as an operator action.
6. Step 5: the cross-repo contract test, once 1-4 are real.
