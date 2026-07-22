# Plan 021 working notes: Correlate and authenticate publication callbacks

Authoritative spec: `plans/021-rebuild-publication-callback-contract.md`. This
file records recon findings and the exact remaining work — read it before
resuming, it will save re-deriving the same investigation.

## Status (2026-07-22): Steps 0-3 and 5 DONE; Step 4 code DONE, real secrets pending the operator

Resumed after the sections below (written during an earlier pass) correctly
identified this as a coordinated cross-repo change that couldn't be split.
This pass landed Steps 1-2 (backend) + Step 3 (frontend) + Step 5 (cross-repo
contract test) together, as that earlier analysis required, plus Step 4's
code on both sides. The only thing NOT done is providing the actual
`WEBHOOK_API_KEY`/`BACKEND_WEBHOOK_TOKEN` secret values and coordinating them
between the backend's deployment and the frontend's GitHub Actions secrets —
that is the operator's own action (their account, their credential), not
something achievable from a chat session, consistent with the standing
constraint applied throughout this whole session (plan 001, plan 023).

### Pre-flight: both STOP conditions checked and cleared before writing code

- **"Stop if `refinery_id` is not present and unique for every newly
  generated post"**: confirmed the DB-id path is reliable — checked 29/30
  real published posts have `refinery_id` (the one exception is a
  manually-authored welcome post, never processed by the automated
  pipeline). Traced `refinery_engine.py::process_single_article`'s
  `_resolve_article_identity(article)` call through to
  `ai_editor.py::process_article(..., explicit_article_id=article_id)` —
  confirmed the exact same identity string ends up in both the DB (via
  `mark_article_published`) and the committed post's `refinery_id`
  frontmatter field, by construction, for every article that goes through
  the real collector→refinery pipeline. Cleared.
- **"Stop if GitHub event data cannot determine a bounded changed-post
  set"**: `git diff --name-only <base>..<head> -- src/content/posts` against
  standard GitHub Actions event data (`github.event.pull_request.base/head.sha`
  for PRs, `github.event.before`/`github.sha` for pushes) is a standard,
  reliable mechanism — implemented as `scripts/utils/publication-ids.js`.
  Cleared.

## Original status (superseded above): PARTIAL

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

---

## Implementation record (2026-07-22 resumption)

Landed in this order, exactly as the "recommended next steps" above
prescribed, each verified against the full backend suite (baseline: 13
pre-existing, unrelated editorial-pipeline failures — confirmed via
`git stash`/`git stash pop` before and after each phase — before moving on):

### 1. Dedup guard fixed first, before touching `mark_article_published`

Added `ArticleRepository.is_article_in_flight_or_done`/
`articles_in_flight_or_done` (checks `processing_status in ("publishing",
"completed")`, not `published_url`/`published_at`) plus `DatabaseManager`
passthroughs. Repointed `apps/refinery/main.py:245`'s dedup guard and
`admin_panel.py`'s two `is_article_published`/`published_ids_in` call sites
(`:705` UI warning, `:2421` list filter) to the new method — the latter two
were technically out of this plan's stated file scope, but leaving them on
the old method would have silently broken their existing behavior (they'd
stop warning about/filtering out articles with an open, still-pending PR)
as an unannounced side effect of this plan's change elsewhere, so fixed as
a mechanical, behavior-preserving one-liner each rather than left as a
regression.

### 2. Backend Steps 1 (remainder) + 2: the state machine

`mark_article_published(article_id, pr_url, refinery_id=None)`:
- Keeps `processing_status = "publishing"` (was `"completed"`) —
  `published_at`/`published_url` are no longer set here at all; they're
  now **only** set by `complete_publication_attempts` on a real deploy.
- Persists `article_metadata["publication"]["refinery_id"]` (defaults to
  `str(article_id)`) — the value `webhook_handler` now matches against.
- Reused the existing (previously orphaned/inert) `frontend_checks`/`state`
  metadata scaffold rather than rebuilding it — confirmed via a dedicated
  Explore-agent investigation that this shape has existed since ancient
  commit `07805b0` and was never read anywhere; it's a dict key this
  session started actually updating, not new plumbing.

`get_publishing_state` now also returns `None` once
`article_metadata["publication"]` exists (a PR was created), even though
`processing_status` is still `"publishing"` — found empirically that
without this, `PROrchestrator.attempt_recovery` would re-fire after
`PUBLISHING_TIMEOUT_SECONDS` (1h) on an article with an already-open PR
just waiting on a slow-but-healthy Content Guard/deploy run, creating a
duplicate PR. Not previously documented in this file; found while reasoning
through the state-machine redesign, not by reading it somewhere.

New: `reject_publication_attempts(refinery_ids, reason)` /
`complete_publication_attempts(refinery_ids, deploy_url)` — match only
`processing_status == "publishing"` rows whose
`article_metadata["publication"]["refinery_id"]` is in the given set
(never a bulk update of every publishing row), idempotent (an
already-completed/rejected row is no longer "publishing" so a replay
matches nothing).

`pr_orchestrator.py::create_pr` now passes its own `article_id` string
parameter through as `refinery_id` — confirmed this is the exact value
`_resolve_article_identity()` also writes into the frontmatter (see the
STOP-condition check above), so DB-side and file-side identity are
identical by construction, not by convention.

`webhook_handler.py` rewritten: matches by `event.publication_ids` via the
two new repository methods; a callback with empty `publication_ids` is
logged and is a no-op (never falls back to branch matching) — this is
Step 1's "reject empty identity lists for publication-state mutations"
requirement, implemented at the handler level as the earlier note said it
must be (the model-level `test_publication_ids_empty_list_accepted` test,
correctly, still passes unchanged).

Updated 5 existing tests that asserted the old (buggy) behavior
(`test_storage_coverage.py`, `test_database.py`,
`test_publishing_state_recovery.py` ×2, `test_refinery_audit_staging.py`,
`test_refinery_engine.py`) and added ~20 new ones covering the new
methods, the duplicate-PR-prevention fix, and ID-based matching
(idempotency, unrelated-id no-op, empty-list no-op).

### 3. Step 4 backend half: fail-closed auth

`verify_webhook_token` now raises 503 when `WEBHOOK_API_KEY` is unset
**and** the runtime environment isn't `"development"` — reused the
existing `get_runtime_config().environment`/`is_production`/`is_staging`
concept (`news_collector/config/settings.py`) rather than inventing a new
environment-tier abstraction, since one already existed and just wasn't
being consulted here. `config.toml`'s default environment is
`"development"`, so today's actual runtime behavior is unchanged unless
someone sets `environment` to anything else without also setting
`WEBHOOK_API_KEY` — exactly the "explicit loopback-only development
setting" the plan asked for.

### 4. Frontend Step 3 + Step 4 (sending half)

In the sibling `noticiencias` repo (see that repo's own commits for the
full diff):
- `scripts/backend-notify.js` refactored to export `buildEnvelope()` /
  `sendWebhookNotification()` (previously a top-level script with no
  importable surface) — adds `publication_ids` to the envelope and an
  `Authorization: Bearer $BACKEND_WEBHOOK_TOKEN` header when the secret is
  set. Never logs the token (verified with a dedicated test).
- `scripts/post-publish-callback.js` rewritten to call those exports
  **directly, in-process** — no more building its own full envelope,
  writing it to a file, and spawning `backend-notify.js` as a subprocess
  pointed at that file. That file-based indirection was the literal
  mechanism producing the double-nested envelope bug (a non-array JSON
  file gets wrapped as `diagnostics: [thatObject]`); calling the exported
  functions directly makes the bug class structurally impossible, not just
  patched.
- New `scripts/utils/publication-ids.js`
  (`getChangedPostRefineryIds({baseSha, headSha, repoRoot})`): `git diff
  --diff-filter=ACM --name-only <base>..<head> -- src/content/posts`,
  parses each changed post's `refinery_id` frontmatter via `gray-matter`
  (already a project dependency). Returns `[]` (never throws) on any git
  failure or missing SHA — a bounded-changed-post-set failure degrades to
  "no articles named," never "guess via branch."
- `content-guard.yml`/`deploy.yml`: both checkouts now use `fetch-depth: 0`
  (the git-diff-based derivation needs the base commit, which a shallow
  checkout wouldn't have); both now pass `GITHUB_BASE_SHA` (from
  `github.event.pull_request.base.sha`/`github.event.before` as
  appropriate) and `BACKEND_WEBHOOK_TOKEN` (from a secret that doesn't
  exist yet — the IDE correctly flags "context access might be invalid,"
  expected until the operator creates it).

**A real bug caught while testing, not by inspection**: spawning
`backend-notify.js` as a subprocess from within a Vitest worker process
and connecting back to a same-process HTTP test server hung indefinitely
in this sandbox (confirmed via a minimal repro: direct in-process `fetch`
to the same server worked instantly; the identical request from a spawned
child process timed out at 5s every time) — a sandbox-specific
child-process network restriction, not a real bug in the script (a bare
`node script.js` against a real standalone server worked fine outside
Vitest). Rather than fight the sandbox, refactored to the exported-function
design above, which is also a **better testing design independent of the
sandbox issue** — no subprocess, no real network, no payload files,
snapshot-style assertions on the exact envelope/headers.

New frontend tests: `tests/publication-ids.test.ts` (7 tests, using real
ephemeral git repos — not mocked git), `tests/backend-notify.test.ts` (11
tests), `tests/post-publish-callback.test.ts` (2 tests, `vi.doMock` on
`sendWebhookNotification` to intercept the envelope without a real
network call).

### 5. Step 5: the cross-repo contract test

`tests/integration/test_publication_callback_contract.py` (backend repo).
Calls the frontend's *real* `buildEnvelope()` via a Node subprocess (one
line of Python `subprocess.run(["node", "--input-type=module"], input=...)`
capturing stdout — no network, no server, just reading the sibling repo's
actual file and running it) to build a realistic envelope, validates it
through the real `parse_webhook_payload`, replays it through the real
`process_validation_result`/`process_publish_complete` against a real
SQLite DB after a real `mark_article_published` transition. Skips
gracefully (`pytest.mark.skipif`) if Node or the sibling repo checkout
isn't present, rather than failing or being silently omitted from CI.

Covers every case the plan's Step 5 names: PR/Content-Guard failure
(rejects the named article), deploy success (completes it, sets a real
`published_url`), replay (asserts identical DB state before/after
replaying the same event), unrelated id (doesn't touch a different
article), auth enabled (both a valid-token 202 that actually completes
the article, and a missing-token 401), and two malformed-envelope cases
(missing required field, an invalid `publication_ids` entry) — both via
the real Pydantic validator, not a hand-rolled check.

### Verify

- Backend: `.venv/bin/python -m pytest tests --ignore=tests/e2e_pipeline`
  → 13 failed (unchanged baseline, confirmed via git-stash diffing before
  committing), 1275 passed (was 1262 before this session's plan-021 work;
  +13 net new tests across the state-machine and contract-test additions).
  `black`/`ruff` clean on every touched file; `mypy` — identical 14
  pre-existing errors (confirmed via the same stash-diff technique),
  zero new ones.
- Frontend: `npm run test:audit` → 38/38 files, 220/220 tests (was
  35/200 before plan 021's frontend work). `npx astro check` — the one
  pre-existing, unrelated `Metadata.astro` error only. `prettier`/`eslint`
  clean.

### What's genuinely still open

- **Real secret values**: `WEBHOOK_API_KEY` (backend deployment
  environment) and `BACKEND_WEBHOOK_TOKEN` (frontend GitHub Actions
  secret) — the operator's own account/credentials, per the standing
  constraint this whole session applied to plan 001/023 too. The code on
  both sides is ready and tested; only the values are missing.
- **No live end-to-end run**: this is a fully verified *contract* — real
  sender code, real backend models, real handler, real DB — but has never
  round-tripped over an actual HTTPS request to a deployed backend
  (matches plan 046's finding that no production deployment exists yet;
  nothing to round-trip against).
- Two admin_panel.py call sites were repointed to preserve their existing
  behavior (see "1. Dedup guard fixed first" above) but weren't otherwise
  audited beyond that — admin_panel.py itself remains explicitly out of
  this plan's stated scope.
