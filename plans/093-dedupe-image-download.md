# Plan 093: Deduplicate the two image-download implementations

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/logic/workflows/refinery_engine.py news_collector/logic/workflows/image_handler.py tests/unit/logic/workflows/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

`RefineryEngine._download_image` and `ArticleImageHandler.download` implement
the identical sequence (guard → mkdir → `RobustRequestsClient` → Content-Type
extension resolution → URL-suffix fallback → write → Astro path), and they have
already started diverging in edge handling and log shape. Any retry/timeout/
extension-mapping fix must land twice or behavior splits by entry path. After
this plan, one implementation owns the behavior and the other delegates.

## Current state

The relevant files, each with one line on its role:

- `news_collector/logic/workflows/refinery_engine.py` — `_download_image` (lines 964-1018)
- `news_collector/logic/workflows/image_handler.py` — `ArticleImageHandler.download` + `CT_TO_EXT` (lines 179-234)

Excerpts (both read in full; bodies match step-for-step):

Engine `refinery_engine.py:964-994`:

```python
def _download_image(self, url: str, slug: str, target_dir: Path) -> str | None:
    """
    Downloads a remote image to the local assets directory.
    Returns the Astro-compatible local path (e.g. "~/assets/images/slug.jpg")
    or None if download fails.
    """
    url = str(url).strip()
    if not url or not url.startswith("http"):
        return None
    ext = None  # resolved after first request below
    assets_dir = target_dir / "src/assets/images"
    assets_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Downloading image from {url}")
    from news_collector.infrastructure.requests_client import RobustRequestsClient
    try:
        with RobustRequestsClient() as client:
            response = client.get(url, timeout=15)
        ct = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        ext = CT_TO_EXT.get(ct)
        ...
```

Handler `image_handler.py:179-204` — same docstring shape, same sequence
(`logger.info("Downloading image from {}", url)` loguru-style is the only
material difference besides which `CT_TO_EXT` each resolves):

```python
def download(self, url: str, slug: str, target_dir: Path) -> str | None:
    """Download a remote image and save it to the local assets directory. ..."""
    from news_collector.infrastructure.requests_client import RobustRequestsClient
    url = str(url).strip()
    if not url or not url.startswith("http"):
        return None
    ...
```

Both end with `filename = f"{slug}{ext}"; local_path.write_bytes(response.content)` and return `f"~/assets/images/{filename}"`, `None` on exception.

Repo conventions that apply here:

- Refactor trigger (§7): "the same mapping logic appears in two modules" — delete one, delegate to the other; prefer a small delegation over a new abstraction (LAW-B9 — no new classes).
- `ArticleImageHandler.download` is the injected/tested seam; the engine method is the duplicate to remove.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Boundaries| `make test-boundaries`   | declared   | all pass |

## Scope

**In scope** (the only files you should modify):

- `news_collector/logic/workflows/refinery_engine.py` (replace `_download_image` body with delegation)
- `news_collector/logic/workflows/image_handler.py` (only if `CT_TO_EXT` ownership needs consolidating — read first; likely no change)
- `tests/unit/logic/workflows/` (delegation test)

**Out of scope** (do NOT touch, even though they look related):

- Download retry/timeout/extension semantics — this plan changes ownership, not behavior.
- `ImageBriefStore.stage_upload` (upload path) — owned by plan 087.
- Any new shared "downloader service" abstraction — delegation, not a new layer.

## Git workflow

- Branch: `advisor/093-dedupe-image-download`
- Conventional commits, e.g. `refactor(workflows): delegate engine image download to ArticleImageHandler`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Map callers and `CT_TO_EXT` ownership

1. `grep -rn "_download_image\|\.download(" news_collector/ apps/ scripts/ | grep -v test` — list every caller of both methods.
2. `grep -n "CT_TO_EXT" news_collector/logic/workflows/refinery_engine.py news_collector/logic/workflows/image_handler.py` — confirm where the mapping is defined vs imported (audit says defined in handler, imported by engine — verify).
3. Confirm the engine has (or can cheaply get) an `ArticleImageHandler` instance at the `_download_image` call site — read the engine `__init__` and the call site(s). Both call sites already accept an injectable `download_fn` per audit; verify.

**Verify**: a caller list with file:line. If the engine has no handler instance and constructing one requires new config plumbing, STOP and report (delegation must stay trivial).

### Step 2: Delegate

Replace the body of `RefineryEngine._download_image` with a thin delegate to the handler instance's `download` (same signature `(url, slug, target_dir)`).
Keep the method (don't break external callers found in Step 1); mark it as a
compatibility delegate in the docstring. Remove the now-unused `CT_TO_EXT`
import in the engine file if nothing else uses it (check first).

**Verify**: `make lint` → exit 0; unified diff of behavior — the only intended runtime difference is log-line format.

### Step 3: Add a delegation/parity test

In `tests/unit/logic/workflows/` (extend the image-handler or engine test file, whichever fits):

1. Fake `RobustRequestsClient` (or monkeypatch the handler's download): engine `_download_image` returns exactly what handler `download` returns for the same inputs (success bytes → Astro path; failure → `None`; non-http URL → `None`).
2. Assert the engine method calls through (spy on the handler instance) rather than re-implementing.

**Verify**: new tests pass; existing image/workflow suites green.

### Step 4: Run the full gates

**Verify**: `make lint && make type && make test && make test-boundaries` → all exit 0.

## Test plan

- New delegation/parity tests (engine → handler pass-through, all three outcome shapes).
- Existing `test_refinery_engine.py` + image-handler tests must pass unchanged (behavior preservation proof).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` all exit 0
- [ ] `RefineryEngine._download_image` body is a delegate (no `RobustRequestsClient`, no `CT_TO_EXT`, no `write_bytes` in it — grep)
- [ ] `CT_TO_EXT` is defined in exactly one module
- [ ] New delegation tests exist and pass
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- The two bodies differ in more than log shape (diff them carefully — any semantic difference in extension fallback order, timeouts, or error handling must be reconciled deliberately and reported, not silently picked).
- Delegation requires new constructor plumbing in the engine.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- Future download-policy changes (timeouts, retries, extension map) now have exactly one owner: `ArticleImageHandler.download`.
- Reviewers: the load-bearing check is the Step 1 semantic diff of the two bodies.
- **Deferred:** unifying `_derive_slug`/`derive_slug` — that's plan 094, do not bundle.
