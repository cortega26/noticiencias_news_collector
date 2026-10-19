# Plan 168: Make the image gate cheap to clear (prompt in the desk, no doomed run)

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. Commit your work in the worktree following the plan's git workflow.
>
> **Drift check (run first)**:
> `git diff --stat 36d5da97..HEAD -- news_collector/contracts/admin.py news_collector/serving/api.py news_collector/logic/workflows/refinery_engine.py news_collector/logic/workflows/image_handler.py apps/admin/src/lib/types.ts apps/admin/src/pages/images.astro apps/admin/src/pages/article.astro tests/test_serving_admin_api.py`
> If any in-scope file changed, read the live version; on a mismatch with the
> excerpts, STOP.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: MEDIUM (publish dispatch semantics + admin UI)
- **Depends on**: none (the gate and briefs already exist)
- **Category**: admin / publication UX
- **Planned at**: commit `36d5da97`, 2026-10-19

## Why this matters

Publishing article #3724 failed at the image gate with
`The source image is not reused without a licence…`. The gate is deliberate
(third-party images, licensing/AdSense), but the recovery path is poor:

1. The brief already contains a complete `generated_prompt`, but the admin
   **never shows it** (`AdminImageBriefItem` has no field; the Images desk only
   renders topic/angle/alt). The operator must open the JSON by hand.
2. The pipeline gate runs **before** refine, and `workflow_runs.status` has a
   closed CHECK constraint — there is no honest "wait for image" state without a
   migration, and no persisted refine to resume. What actually happens is a
   **failed run** that the operator must diagnose.
3. For the `missing_source_image` / `image_download_failed` reasons, the engine
   sets no blocked-error message at all (`refinery_engine.py:634-640`), so the
   run reports a generic failure.

The honest fix: make the prompt one click away, make "publish again" one click
after the upload, and **refuse to start a run that is guaranteed to fail** on a
missing image (return a structured `image_required` instead of a failed run).

**Out of scope / explicit non-goal:** calling the ChatGPT subscription.
A Plus/Pro subscription is not an API; programmatic generation needs an API key
and per-image billing, and the contract has no AI-credit field. The operator
generates the image (ChatGPT or licensed stock) and uploads it.

## Current state

- `news_collector/contracts/admin.py:436-449` — `AdminImageBriefItem` (no
  prompt field).
- `news_collector/serving/api.py:2562` — builds `AdminImageBriefItem` from the
  store; the list route is around it.
- `apps/admin/src/lib/types.ts:210-222` — mirror type.
- `apps/admin/src/pages/images.astro:70-105` — brief card with topic/angle/alt
  inputs, `Guardar cambios` and `Añadir archivo`; no prompt, no retry.
- `news_collector/logic/workflows/refinery_engine.py:630-641` — sets
  `_last_blocked_error` only when `img_resolution.message` is truthy.
- `news_collector/logic/workflows/image_handler.py:150-200` — the
  `third_party_image_blocked` branch sets a message; the logo/download branches
  do not.
- `tests/test_serving_admin_api.py` — existing admin API tests (dispatch,
  publish 409 semantics); extend it.
- The brief for #3724:
  `data/image-briefs/2026-10-17-neandertal-herido-y-cuidado-senal-de-empatia-hace-75-000-anos.json`
  (`status=needs_editorial_image`, full `generated_prompt`).

## Commands you will need

| Purpose        | Command                                                        | Provenance | Expected |
|----------------|----------------------------------------------------------------|------------|----------|
| Install        | `make bootstrap`                                               | declared   | exit 0   |
| Admin install  | `make admin-install`                                           | declared   | exit 0   |
| Backend tests  | `make test`                                                    | declared   | all pass |
| Contracts      | `make test-contracts`                                          | declared   | all pass |
| Boundaries     | `make test-boundaries`                                         | declared   | 3 passed |
| Admin gates    | `make admin-test` / `make admin-lint` / `make admin-build`     | declared   | exit 0   |
| Lint/types     | `make lint` / `make type` (committed)                          | declared   | exit 0   |
| Docs/inventory | `make docs-check` / `make inventory-check`                     | declared   | exit 0   |
| Ledger         | `make plans-ledger-check`                                      | declared   | OK       |

Provenance: all `declared`.

## Scope

**In scope**:
- `news_collector/contracts/admin.py` — `generated_prompt` on the brief item
- `news_collector/serving/api.py` — expose it; pre-dispatch image gate
- `news_collector/logic/workflows/refinery_engine.py` — blocked-error mapping
- `news_collector/logic/workflows/image_handler.py` — carry a reason on every
  unresolved branch (smallest change that lets the engine name the cause)
- `apps/admin/src/lib/types.ts`, `apps/admin/src/pages/images.astro`,
  `apps/admin/src/pages/article.astro` — prompt + copy + retry; handle the
  structured 409
- `tests/test_serving_admin_api.py` (+ a focused engine test if one exists) —
  regression tests
- `docs/` — one short section on the image-required flow (images desk)

**Out of scope**: new run statuses/migrations, API image generation, browser
automation, the prompt template, the licensing policy, the frontend repo.

## Steps

### Step 1: Expose the prompt (contract + API + type)

1. Add `generated_prompt: Optional[str] = None` to `AdminImageBriefItem`.
2. Populate it where the item is built (`api.py:2562`).
3. Mirror it in `apps/admin/src/lib/types.ts`.
4. Test: the list endpoint returns the prompt for a seeded brief (extend
   `tests/test_serving_admin_api.py` with a tmp brief store or the existing
   fixture pattern).

**Verify**: `make test-contracts` + the focused admin test green.

### Step 2: Desk UX (prompt + copy + retry)

5. `images.astro`: in each card add a `<details>` with the prompt in a `<pre>`
   (escaped), a **Copiar prompt** button (`navigator.clipboard.writeText`), and —
   when `status === 'editorial_image_ready'` — a **Publicar de nuevo** button
   that calls `startPublish({ articleId: Number(b.article_id) })` and shows the
   run id (reuse the article page's pattern).
6. Escape everything; no `innerHTML` with raw prompt content outside `esc()`.
7. `apps/admin` vitest: if the desk has a component test harness, add a case for
   the copy payload; otherwise add a minimal DOM test for the rendered prompt and
   note the limitation. Do not weaken existing tests.

**Verify**: `make admin-lint`, `make admin-test`, `make admin-build`.

### Step 3: Name the blocked reason

8. In `image_handler.py`, add a `reason` to the unresolved result on every
   branch that queues a brief (`missing_source_image`, `third_party_image_blocked`,
   `image_download_failed`, logo). Keep the existing `message` behaviour.
   (If `ImageResolution` is a frozen dataclass, add the field with a default.)
9. In `refinery_engine.py`, set `_last_blocked_error` for **every** unresolved
   image, using `img_resolution.message` when present and otherwise a message
   built from the reason (include the article id/slug if the resolution carries
   it). Keep the persisted-attempt behaviour.

**Verify**: a focused engine/handler test proves a `missing_source_image`
failure now reports that reason (extend the existing image tests).

### Step 4: Refuse the doomed run at dispatch

10. In `admin_publish`, when `article_id` is provided, load the brief for that
    article (use the existing `ImageBriefStore`); if a brief exists with
    `status == "needs_editorial_image"`, raise a **409** with a structured
    detail:
    ```json
    {"detail": {"error_code": "image_required", "slug": "...", "article_id": 3724, "prompt": "..."}}
    ```
    Do **not** create a run. An `editorial_image_ready` brief proceeds normally.
    `article_url` requests keep the current behaviour (the article does not exist
    yet).
11. `article.astro`: when the publish call fails with `ConflictError` and
    `body.detail.error_code === "image_required"`, render a clear message with a
    link to `/images` (and optionally the prompt in a `<details>`); keep the
    existing "already running" handling when the detail has a run id.
12. Tests: dispatch with a seeded `needs_editorial_image` brief → 409 with the
    prompt and **no** run; with `editorial_image_ready` → 202; without a brief →
    202 (current behaviour).

**Verify**: focused tests green; the existing publish tests still pass.

### Step 5: Gates

13. `make lint`, `make type` (post-commit), `make test`, `make test-contracts`,
    `make test-boundaries`, `make admin-test`, `make admin-lint`,
    `make admin-build`, `make docs-check`,
    `make inventory-refresh && make inventory-check`, `make plans-ledger-check`.

**Verify**: all exit 0.

## Test plan

- Backend: brief item includes the prompt; dispatch 409 `image_required` /
  202 ready / 202 absent; engine reports the reason for a message-less failure.
- Admin: desk renders the prompt and copies it; retry button calls the right
  endpoint; article page renders the image-required message.
- Manual smoke (optional, after merge): publish #3724 → 409 with the prompt;
  upload the generated image → retry → run starts.

**Verify**: `make test` + `make admin-test` green.

## Done criteria

- [ ] The Images desk shows and copies the full `generated_prompt`
- [ ] A `needs_editorial_image` brief produces a 409 `image_required` **without** a run
- [ ] `editorial_image_ready` and no-brief cases still start a run
- [ ] Every unresolved image reason is named in the run error
- [ ] No new run status, no migration, no API image generation
- [ ] Backend + admin + contracts + boundaries + docs + inventory + ledger green
- [ ] `git diff --name-only main...HEAD` lists only the in-scope files
- [ ] Ledger row 168 updated by the reviewer

## STOP conditions

- The 409 shape breaks the existing "already running" contract in a way the UI
  cannot distinguish → report; do not overload the same payload.
- The brief lookup has side effects or writes to `data/` during a GET/validation
  → report.
- The prompt is not available for old briefs (backfill would require rewriting
  data) → render "prompt unavailable" and report; do not regenerate silently.
- Any change would require auto-generating or auto-publishing an image → STOP
  (out of scope; needs an explicit provider/billing/policy decision).

## Maintenance notes

- The prompt is generated at brief creation; editing brief fields does **not**
  regenerate it (existing behaviour). If that changes, keep the desk's copy
  button reading the stored prompt.
- The dispatch gate mirrors the worker's image resolution; if the allowlist or
  resolution logic changes, update both and keep the test that proves they agree.
