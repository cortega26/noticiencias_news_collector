# Plan 169: AI-image provenance, caption/credit and editorial policy (AdSense)

> **Executor instructions**: This plan has two phases in **two repositories**.
> Phase F runs in `../noticiencias` (frontend) and must be merged **first**;
> Phase B runs in this repository and merges after F. Follow each phase's steps,
> run every verification, and stop on the STOP conditions. Do not improvise.
>
> **Drift check (run first, in this repo)**:
> `git diff --stat 1ebe5398..HEAD -- news_collector/contracts/frontend_schema.py news_collector/contracts/image_brief.py news_collector/logic/workflows/image_briefs.py news_collector/components/editorial/editorial_publication_artifact.py news_collector/serving/api.py apps/admin/src/lib/types.ts apps/admin/src/pages/images.astro tests/test_contracts_sync.py`
> Plus, in `../noticiencias`:
> `git diff --stat <pin>..origin/main -- src/content.config.ts src/layouts/PostLayout.astro src/components/ds/organisms/Footer.astro src/pages/`
> If any in-scope file changed, read the live text; on a mismatch, STOP.

## Status

- **Priority**: P2 (AdSense/misrepresentation risk)
- **Effort**: M (two repos)
- **Risk**: MEDIUM (cross-repo contract, critical by governance)
- **Depends on**: frontend merge first (order below)
- **Category**: publication contract / editorial transparency
- **Planned at**: commit `1ebe5398`, 2026-10-19

## Why this matters

The #3724 hero is an AI-generated illustration. It was disclosed manually (body
note + `image_alt` prefix) and the frontend already renders `image_alt` as a
visible `<figcaption>`. But:

1. The publisher does not record **provenance** for editorial images, so every
   future AI image needs a manual edit to be labeled.
2. The contract has no dedicated **caption/credit** fields; the visible caption
   reuses the alt text, and the alt must then carry both the disclosure and the
   description (awkward for accessibility).
3. There is no site-wide **AI/editorial policy** page for reviewers/readers.

AdSense rejection risk is about misleading content and weak site transparency.
The fix: provenance at the brief, automatic caption/credit in the published
frontmatter, a dedicated visible caption, and a policy page.

## Current state

- `news_collector/contracts/frontend_schema.py:163-164` — `image`,
  `image_alt`; `AstroPost` is the mirror.
- `apps/../noticiencias/src/content.config.ts:63-72` — Zod `image`/`image_alt`
  (top-level); parity is **strict set equality** (`tests/test_contracts_sync.py::test_frontend_schema_field_parity`), so both repos must add the same top-level fields.
- `../noticiencias/src/layouts/PostLayout.astro:213-228` — the hero
  `<figure>` already renders `<figcaption>{imageAlt}</figcaption>`.
- `news_collector/components/editorial/editorial_publication_artifact.py:94-103,240-250`
  — `PublicationArtifactInput.image_alt` is written to the frontmatter; the alt
  is recomputed with the Spanish title.
- `news_collector/contracts/image_brief.py:37-58` — `ImageBriefModel`
  (`extra="forbid"`), no provenance field.
- `news_collector/logic/workflows/image_briefs.py` — `stage_upload(...)` writes
  the brief; the Images desk uploads via `POST /v1/admin/images/{slug}/upload`.
- Merge order matters: the backend parity test checks out the frontend `main`;
  a backend-first merge would fail `missing_in_zod` until F lands. **Merge F
  first**, then rebase/re-run B.

## Phase F — frontend (`../noticiencias`, PR)

**Branch**: `feat/ai-image-caption-policy`. **Do not** touch the backend repo.
**Do not** change existing posts (only schema/render/policy/footer/tests).

1. `src/content.config.ts`: add two optional top-level fields next to
   `image_alt`:
   ```ts
   image_caption: z.string().optional(),
   image_credit: z.string().optional(),
   ```
2. `src/layouts/PostLayout.astro`: derive
   `const imageCaption = post.image_caption ?? imageAlt;`
   `const imageCredit = post.image_credit ?? '';`
   and render the figcaption as the caption plus an optional credit span:
   `{imageCaption}{imageCredit && <span> · {imageCredit}</span>}` (keep the
   existing styling; escape is automatic in Astro).
3. **Policy page**: `src/pages/uso-de-ia.astro` (Spanish, ~400-600 words):
   - how AI is used (summaries, translation, editorial images),
   - **image labeling**: AI-generated or AI-assisted images carry
     `image_caption`/`image_credit` and are never presented as photographs of
     real events,
   - human oversight, source citation, correction policy, contact.
   Use the site's existing layout/components (`Layout`, prose classes).
4. `src/components/ds/organisms/Footer.astro`: add a link to `/uso-de-ia`
   (same style as the neighbouring legal links).
5. Tests/gates: `npm ci` if needed; `npm run lint`, `npx astro check`,
   `npm run build`, `npm run test:audit`. Add a vitest only if a pure helper is
   extracted; otherwise state that the page is covered by `astro check`/build.
6. Commit, push the branch, open a PR against `main` with a body explaining the
   cross-repo field addition and the merge order (this PR first). Wait for
   checks; merge when green. **Report the merge commit.**

## Phase B — backend (this repo, PR/worktree)

**Branch**: `advisor/169-image-provenance`. Base: current `main` **after F is
merged** (rebase if needed so the parity test sees the new fields).

1. `news_collector/contracts/frontend_schema.py`: add
   `image_caption: Optional[str] = None`, `image_credit: Optional[str] = None`
   to `AstroPost` (top-level, matching the Zod fields).
2. `news_collector/contracts/image_brief.py`: add
   `image_origin: Literal["unknown", "ai_generated", "licensed", "original"] = "unknown"`
   to `ImageBriefModel` (extra=forbid is fine for a new optional field).
3. `news_collector/logic/workflows/image_briefs.py`: `stage_upload(...,
   image_origin: str | None = None)` persists it (validate the literal).
4. `news_collector/serving/api.py`: the upload route accepts an optional
   `image_origin` form field and passes it; `AdminImageBriefItem` exposes
   `image_origin` (and the prompt already exposed).
5. Admin desk (`types.ts`, `images.astro`): a select **Origen** in each brief
   card (`IA generada`, `Licencia`, `Original`, `Desconocido`), included in the
   upload/save request; show it in the card. The article page's image-required
   message stays.
6. Publisher (`editorial_publication_artifact.py` + the engine/input that
   carries the brief data):
   - carry `image_origin` (and the brief's caption/credit if present) into
     `PublicationArtifactInput`;
   - when `image_origin == "ai_generated"`, set:
     `image_caption = "Ilustración generada con IA. No es una fotografía del hallazgo."`
     (or a configurable variant) and
     `image_credit = "Noticiencias / IA generativa"`;
   - prefix the alt **once** with `"Ilustración generada con IA: "` (do not
     duplicate if already prefixed); the YAML serializer must quote values with
     a colon (the #312 breakage — cover it with a serialization test);
   - other origins: no AI caption; `licensed`/`original` may carry a credit if
     the brief provides one (optional field, leave empty otherwise).
7. Tests:
   - parity test (with the frontend present) passes with the new fields;
   - brief provenance persists/round-trips; invalid origin rejected;
   - artifact serialization: AI origin → caption/credit/alt quoted and valid
     YAML; licensed/unknown → no AI caption;
   - admin API/desk tests updated.
8. Docs: `docs/PIPELINE_CONTRACTS.md` (new optional fields + merge order),
   `docs/PRODUCT_FLOW.md` (image provenance), and a short note in the Images
   desk docs.
9. Gates: `make lint`, `make type` (committed), `make test`,
   `make test-contracts` (with the sibling present), `make test-boundaries`,
   `make admin-test`, `make admin-lint`, `make admin-build`, `make docs-check`,
   `make inventory-refresh && make inventory-check`, `make plans-ledger-check`.

## Done criteria

- [ ] Frontend PR merged: schema fields, visible caption/credit, `/uso-de-ia`, footer link; checks green
- [ ] Backend parity passes with the frontend fields; publisher emits caption/credit/alt for AI images and valid YAML
- [ ] Brief provenance persists; the desk lets the operator choose it; unknown/licensed do not claim AI
- [ ] Admin + backend + contracts + boundaries + docs + inventory + ledger green
- [ ] No manual edit is needed for future AI images to be labeled
- [ ] Ledger row 169 updated by the reviewer (after both merges)

## STOP conditions

- The frontend schema cannot accept the optional fields without a `schema_version` bump/backfill → report; do not bump without a migration plan.
- The parity test cannot be made green in both merge orders without weakening it → report the exact order needed; do not relax the test.
- A publisher change would rewrite existing posts/backfill → STOP (only new publications).
- The policy page would require a legal review you cannot perform → draft it and mark it for review; do not block the technical phases.
- Any secret or credential is needed → STOP.

## Maintenance notes

- Merge order is mandatory: **F then B**; the backend parity gate is strict.
- The caption/credit fields are optional; older posts render exactly as today.
- The AI disclosure text lives in the publisher (one place); the Images desk only records provenance.
