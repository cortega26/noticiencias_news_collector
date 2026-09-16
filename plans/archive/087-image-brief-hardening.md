# Plan 087: Harden the image-brief store — slug traversal guard plus bounded, type-checked uploads

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/logic/workflows/image_briefs.py news_collector/serving/api.py tests/unit/logic/workflows/ tests/test_serving_admin_api.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

Two hardening gaps share one trust boundary (the admin image-brief surface).
First, `ImageBriefStore.brief_path()` interpolates the URL-supplied `{slug}`
directly into a filesystem path with no traversal check, so an authenticated
caller can read/write JSON outside the briefs/uploads directories. Second, the
upload endpoint reads an unbounded body and trusts the client filename's
extension, and the staged file is later copied into publish assets preserving
that extension — enabling disk/memory abuse and persistence of executable asset
types. After this plan, slugs are allowlisted + containment-checked, uploads
are size-bounded, and only genuine image types reach the asset pipeline.

## Current state

The relevant files, each with one line on its role:

- `news_collector/logic/workflows/image_briefs.py` — `ImageBriefStore`: brief paths, upload staging, asset materialization (lines 49-104, 210-262)
- `news_collector/serving/api.py` — `POST /v1/admin/images/{slug}/upload` (lines 1849-1887)
- `news_collector/logic/workflows/target_repo_writer.py` — exemplar `relative_to` containment guard (lines 68-80)

Excerpts of the code as it exists today:

`news_collector/logic/workflows/image_briefs.py:60-76` — raw interpolation:

```python
def brief_path(self, slug: str) -> Path:
    return self.briefs_dir / f"{slug}.json"
...
def load_brief(self, slug: str) -> ImageBriefModel | None:
    path = self.brief_path(slug)
    if not path.exists():
        return None
    return ImageBriefModel.model_validate_json(path.read_text(encoding="utf-8"))
```

`news_collector/logic/workflows/image_briefs.py:219-221,259-261` — client-controlled extension, trusted end to end:

```python
safe_ext = Path(filename).suffix.lower() or ".png"
staged_path = self.uploads_dir / f"{brief.slug}{safe_ext}"
...
extension = source_path.suffix.lower() or ".png"
destination = target_assets_dir / f"{brief.slug}{extension}"
```

`news_collector/serving/api.py:1849-1854,1871-1873` — slug from the route, unbounded read:

```python
@app.post(
    "/v1/admin/images/{slug}/upload",
    response_model=AdminImageBriefUploadResult,
)
def admin_upload_image_brief(
    slug: str,
...
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Empty file upload")
```

The exemplar to copy — `target_repo_writer.py:71-80`:

```python
resolved_target = target_file_path.resolve()
resolved_posts = posts_dir.resolve()
# NC-BE-015 S0 GUARD: Path Traversal Check
try:
    resolved_target.relative_to(resolved_posts)
except ValueError as err:
    raise ValueError(...)
```

Repo conventions that apply here:

- LAW-B2/B5: slugs elsewhere go through `slugify` + guards; this store must match that discipline, not invent its own alphabet (slugs are produced by `derive_slug` → `{date}-{slugified}`).
- The admin GUI sends `accept="image/*"` — a client hint only; the server allowlist is the real control.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Security  | `make security`          | declared   | exit 0, no new HIGH findings |

## Scope

**In scope** (the only files you should modify):

- `news_collector/logic/workflows/image_briefs.py`
- `news_collector/serving/api.py` (upload endpoint + any other `{slug}` image-brief route that calls `load_brief`/`stage_upload`, e.g. the update route above line 1849 — read it first)
- New tests: `tests/unit/logic/workflows/test_image_briefs_security.py` (create)

**Out of scope** (do NOT touch, even though they look related):

- `target_repo_writer.py` — exemplar only, already guarded.
- The Astro GUI upload component — client hints are not controls; server-only change.
- Changing which image types the *frontend* can render — allowlist is upload/storage-scoped.

## Git workflow

- Branch: `advisor/087-image-brief-hardening`
- Conventional commits, e.g. `fix(security): guard image-brief slug paths and bound uploads`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Allowlist slugs + containment-check resolved paths

In `news_collector/logic/workflows/image_briefs.py`:

1. Add a module-level slug guard: `^[A-Za-z0-9][A-Za-z0-9_-]*$` (matches what
   `derive_slug`/`slugify` can produce: date prefix + slugified base). Reject
   anything else with `ValueError` naming the offending slug (never echo it
   into logs verbatim beyond the error itself — slugs are operator input, fine
   to include in the exception message).
2. Apply it at the top of `brief_path()` — the single choke point used by
   `load_brief`, `save_brief` (check it routes through `brief_path`), and
   `list_briefs` (stems of `*.json` — must pass the guard too; verify).
3. Additionally resolve + `relative_to` containment in `brief_path` (copy the
   `target_repo_writer.py:71-80` pattern against `self.briefs_dir`) as
   defense-in-depth, and the same against `self.uploads_dir` in `stage_upload`.
4. In the serving routes, catch `ValueError` from the store and raise
   `HTTPException(422)` (check the update route ~line 1830 first — if it calls
   `load_brief(slug)` with the raw path param, it gets the guard for free but
   needs the 422 mapping).

**Verify**: `.venv/bin/python -m pytest tests/unit/logic/workflows/ -q` → pass; quick probe via python REPL: `ImageBriefStore(Path(tmp)).brief_path("../x")` raises `ValueError`.

### Step 2: Bound and type-check uploads

1. In `admin_upload_image_brief` (`api.py:1871`): replace `file.file.read()`
   with a capped read — read in chunks (e.g. 1 MiB) up to `MAX_UPLOAD_BYTES`
   (define as module constant, 10 MiB, a generous ceiling above any GUI-produced
   hero image). If the cap is exceeded → `HTTPException(413)`. Also honor
   `Content-Length` early-reject when present and over cap.
2. In `stage_upload`: allowlist extensions to
   `{".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif"}` (normalize `.jpeg`→`.jpg`
   like the downloaders do). Anything else → `ValueError` (mapped to 422).
3. Add magic-byte verification for the allowed types (PNG `89 50 4E 47…`, JPEG
   `FF D8 FF`, GIF `GIF8`, WebP `RIFF....WEBP`, AVIF `....ftypavif`) on the
   uploaded `content` before writing. NOTE: Python 3.13 removed stdlib `imghdr`
   — implement the byte check locally (~20 lines), do NOT add a new dependency.
   Mismatch → `ValueError` (422).
4. `materialize_uploaded_asset` needs no change once the staged extension is
   constrained — verify by reading it (lines 245-262) and confirm the extension
   can now only come from the allowlist.

**Verify**: `make lint` → exit 0.

### Step 3: Add boundary tests

Create `tests/unit/logic/workflows/test_image_briefs_security.py`:

- Traversal slugs (`../x`, `/abs`, `a/b`, `..`, empty) → `ValueError` from `brief_path`/`load_brief`.
- Legit `derive_slug` output round-trips (guard accepts what the store itself produces — pin with 2-3 representative slugs).
- `stage_upload` with `.svg`/`.html`/no-extension filename → `ValueError`; PNG bytes with `.png` → staged; JPEG bytes labeled `.png` → `ValueError` (magic mismatch).
- Oversize content → 413 at the API level (add to `tests/test_serving_admin_api.py` next to the image-brief tests, or TestClient-level in the new file if the app fixture is importable there — check how existing serving tests build the app first).

**Verify**: new tests pass; full `make test` green.

### Step 4: Run the full gates

**Verify**: `make lint && make type && make test && make security` → all exit 0 with no new HIGH findings.

## Test plan

- New `tests/unit/logic/workflows/test_image_briefs_security.py` (traversal, allowlist, magic bytes, legit-slug acceptance).
- API-level oversize/dissallowed-type cases (413/422) following existing serving-test patterns.
- Existing image-brief/workflow suites must stay green (guard must accept every slug the store itself generates).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make security` all exit 0
- [ ] `grep -n "briefs_dir / f\"{slug}\"" news_collector/logic/workflows/image_briefs.py` → no unguarded interpolation remains (guard precedes it)
- [ ] `grep -n "\.file\.read()" news_collector/serving/api.py` → no unbounded read remains
- [ ] Traversal-shaped slugs return 422 (not 404/500) at the API boundary
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A legit slug the system produces (briefs already on disk under `data/`) fails the new guard — the allowlist is wrong, report samples (names only) instead of widening blindly.
- Pillow or another imaging lib is actually required (it isn't per this plan — magic bytes suffice; if you disagree, stop and explain).
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching the Astro GUI or frontend serving config.

## Maintenance notes

- If new image types are ever needed (e.g. SVG brand marks), extend the allowlist + magic table together — never the extension list alone.
- `MAX_UPLOAD_BYTES` lives next to the route; if the GUI hero pipeline changes resolutions, revisit the ceiling.
- Reviewers: confirm staged-asset serving context (direct-open vs `<img>` embed) stays non-executing for the allowed types.
- **Deferred:** `validate_url_safety` TOCTOU/redirect hardening and headless-fetcher SSRF boundary — separate network-fetch findings, not this store.
