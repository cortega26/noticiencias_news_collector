# Plan 169 (revision 2): AI-image provenance and automatic labeling (no contract change)

> **Revision 2 (2026-10-19).** The first design added `image_caption`/`image_credit`
> to the cross-repo contract. That creates a strict-parity deadlock: each repo's
> check reads the other repo's `main`, so neither PR can be green before the
> other merges, and one `main` stays red during the transition. The frontend
> **already renders `image_alt` as the visible `<figcaption>`** under the hero,
> so a dedicated caption field is not required to disclose. Revision 2 keeps the
> contract untouched: the publisher labels the image **in the alt**, which is
> visible under the image, and the frontend policy page (separate PR) explains
> the labeling. No body note (the user explicitly rejected repetition in prose).
>
> **Executor instructions**: follow the steps, run every verification, stop on
> STOP conditions. Do not improvise.
>
> **Drift check**: `git diff --stat f7b4c2e2..HEAD -- news_collector/contracts/image_brief.py news_collector/logic/workflows/image_briefs.py news_collector/logic/workflows/image_handler.py news_collector/components/editorial/editorial_publication_artifact.py news_collector/serving/api.py apps/admin/src/lib/types.ts apps/admin/src/pages/images.astro tests/`

## Status

- **Priority**: P2 (AdSense / transparency)
- **Effort**: S-M
- **Risk**: LOW-MEDIUM (admin upload contract; no cross-repo contract)
- **Depends on**: frontend PR #313 (policy page + note removal; independent)
- **Category**: editorial provenance
- **Planned at**: commit `f7b4c2e2`, 2026-10-19

## Why this matters

The #3724 AI illustration is disclosed only because an operator edited the post
by hand (alt prefix; the frontend shows it as the caption). Future AI images
would ship unlabeled. The publisher must record provenance and label
automatically, without a cross-repo contract change and without repeating the
disclosure in the article body.

## Current state

- `news_collector/contracts/image_brief.py:37-58` — `ImageBriefModel`
  (`extra="forbid"`), no provenance.
- `news_collector/logic/workflows/image_briefs.py` — `stage_upload(...)`
  persists the brief (asset + alt + editable fields).
- `news_collector/serving/api.py` — `POST /v1/admin/images/{slug}/upload`
  (`file` + optional form fields) and `GET /v1/admin/images`.
- `news_collector/logic/workflows/image_handler.py:~130-150` — a resolved
  editorial brief supplies `image_url` and `image_alt` (from `draft_alt_text`).
- `news_collector/components/editorial/editorial_publication_artifact.py:240-250`
  — writes `image`/`image_alt` into the frontmatter; the YAML serializer quotes
  values with colons (verified by the #312 fix).
- `../noticiencias/src/layouts/PostLayout.astro:213-228` — renders
  `<figcaption>{imageAlt}</figcaption>`, so the alt prefix is the visible label.
- `apps/admin/src/pages/images.astro` — upload form (file + alt/topic fields).

## Scope

**In scope**: `contracts/image_brief.py`, `logic/workflows/image_briefs.py`,
`logic/workflows/image_handler.py`, `components/editorial/editorial_publication_artifact.py`,
`serving/api.py`, `apps/admin/src/lib/types.ts`, `apps/admin/src/pages/images.astro`,
tests, `docs/PRODUCT_FLOW.md` (provenance note).

**Out of scope**: `frontend_schema.py`, the frontend repo, new run statuses,
the licensing gate, body-text disclosure (explicitly rejected).

## Steps

1. **Provenance field**: add
   `image_origin: Literal["unknown", "ai_generated", "licensed", "original"] = "unknown"`
   to `ImageBriefModel`; `stage_upload(..., image_origin=None)` validates and
   persists it (default stays `unknown`).
2. **API + admin**: the upload route accepts an optional `image_origin` form
   field; `AdminImageBriefItem` exposes it; the desk shows a **Origen** select
   (`IA generada`, `Licencia`, `Original`, `Desconocido`) and sends it on upload;
   the card displays the stored origin.
3. **Publisher labeling**: when a resolved brief has
   `image_origin == "ai_generated"`:
   - prefix the alt **once** with `"Ilustración generada con IA: "` (idempotent:
     do not duplicate if already prefixed), preserving the descriptive text;
   - do **not** add any body note;
   - log the provenance used (`image_origin=ai_generated`).
   Other origins leave the alt unchanged. The frontend renders the alt as the
   visible caption, which is the disclosure.
4. **Tests**:
   - brief round-trip persists/rejects an invalid origin;
   - the upload route stores the form value;
   - the publisher prefixes the alt exactly once for AI, not for
     licensed/original/unknown, and the YAML stays valid (colon quoting);
   - admin desk test for the select/serialized payload.
5. **Docs**: one paragraph in `docs/PRODUCT_FLOW.md`: provenance is recorded at
   upload; AI images are labeled in the visible caption (alt-based); no body note.
6. **Gates**: `make lint`, `make type` (committed), `make test`,
   `make test-contracts`, `make test-boundaries`, `make admin-test`,
   `make admin-lint`, `make admin-build`, `make docs-check`,
   `make inventory-refresh && make inventory-check`, `make plans-ledger-check`.

## Done criteria

- [ ] Brief provenance persists and is visible in the desk
- [ ] AI-generated briefs get the alt prefix exactly once; the visible caption shows it
- [ ] No body note; other origins are untouched
- [ ] Admin/backend/contracts/boundaries/docs/inventory/ledger green
- [ ] `git diff --name-only main...HEAD` lists only the in-scope files
- [ ] Ledger row 169 updated by the reviewer

## STOP conditions

- A cross-repo contract change is required (it is not: the alt is existing).
- The alt is not rendered as a caption in the frontend (verify before starting).
- A publisher change would rewrite existing posts (it must only affect new publications).
- Any secret is needed.
