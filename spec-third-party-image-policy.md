# Spec — third-party source images are not reused as the hero image

## Problem

`ArticleImageHandler.resolve` (path 2) downloads the `image_url` that the
collector scraped from the source article and publishes it as the article's
hero image. That image is the source outlet's (or its photographer's) work.
Nothing in the pipeline records a reuse licence for it, so every published
article inherits an image of unverified provenance. The frontend audit of
2026-10-12 found 38 of 49 hero images without a verified licence, and
Google's AdSense review treats media copied from other sites without added
value as low-value content (`docs/products/adsense-2026-10/LEDGER.md` in the
frontend repo, cause B).

## Goals

1. By default, an `http(s)` source image is **not** downloaded. The article is
   routed to the editorial image queue (an `ImageBrief` with reason
   `third_party_image_blocked`), exactly like an article with no image, and the
   publication is blocked until an editorial image is staged (path 1, the
   Images desk upload) or the article already carries a local image (path 3).
2. A host can be allowed explicitly through `REMOTE_IMAGE_ALLOWLIST`
   (or the `remote_image_hosts` constructor argument). The default is empty.
   Adding a host requires a licence record in the frontend
   `docs/image-rights-register.md`.
3. No change to: staged editorial brief priority (path 1), local-path
   pass-through (path 3), missing/placeholder image (path 4), site-logo
   handling, alt-text handling, the download implementation itself.

## Design

- `news_collector/logic/workflows/image_handler.py`
  - `REMOTE_IMAGE_ALLOWLIST: frozenset[str] = frozenset()`.
  - `ArticleImageHandler(image_briefs, *, remote_image_hosts=None)`; `None`
    means the module constant.
  - `_remote_image_allowed(url)`: lowercased hostname without a leading
    `www.`; allowed when it equals an allowlisted host or is a subdomain of
    one (`host == h or host.endswith("." + h)`), so `evilexample.com` and
    `example.com.evil.net` do not match `example.com`.
  - Path 2: when not allowed, log a warning, queue the brief with reason
    `third_party_image_blocked`, return `ImageResolution(resolved=False,
    queued_brief=True, message=...)`. The message reaches the operator through
    `RefineryEngine._last_blocked_error`.
- `news_collector/contracts/image_brief.py`: add `third_party_image_blocked`
  to the `ImageBriefReason` literal (same precedent as `missing_alt_text`:
  the API exposes `reason` as a plain string, so no OpenAPI change).

## Verification

- Unit (`tests/decompose_refinery/test_image_handler.py`):
  - default blocks an `https` image, never calls the download hook, queues a
    `third_party_image_blocked` brief and returns `resolved=False`;
  - allowlisted host and its subdomain download as before; look-alike hosts
    do not;
  - the module default allowlist is empty (guard against silent widening);
  - staged brief and local path keep priority/behaviour.
- Existing publication tests use `https://example.com/...` images with a
  mocked downloader. A session-wide autouse fixture in `tests/conftest.py`
  allows `example.com` for them; the policy tests above build their own
  handler and do not use that default.
- Commands: `make lint`, `make type`, `make test`, `make test-contracts`,
  `make test-boundaries`, `make quality-gate`, `make docs-check`,
  `make plans-ledger-check`, `make inventory-check`.

## Operator impact

An article whose source image is blocked now stops at "Needs editorial image"
in the Images desk instead of publishing the scraped image. Upload an
original or licensed image there (the brief carries a ready-made prompt) and
publish again.
