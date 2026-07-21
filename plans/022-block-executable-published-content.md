# Plan 022: Block executable generated content and serialize JSON-LD safely

> **Executor instructions**: Coordinate backend and frontend changes. Run each repository's checks and update plan 022 in the backend index only after both sides pass.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- news_collector/components/editorial/ai_editor.py tests/unit/editorial/test_generated_article_guardrails.py`; in `../noticiencias`: `git diff --stat 0cdca74..HEAD -- src/pages/'[...slug].astro' src/layouts/PostLayout.astro src/components/ds/molecules/Breadcrumbs.astro src/utils tests scripts`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: backend `e43bd30`, frontend `0cdca74`, 2026-07-21

## Why this matters

Original source HTML is cleaned before the LLM, but the LLM's final Markdown is only checked for placeholders, headings, and length before publication. Astro renders that output as executable Markdown/MDX. Separately, article-controlled titles and excerpts are inserted into inline JSON-LD using raw `JSON.stringify`, allowing a closing script sequence to escape the data block.

## Current state

- Backend `ai_editor.py:299-327` is the fail-closed generated-article validator; extend this boundary rather than adding repair logic in presentation components.
- `ai_editor.py:1605-1609` cleans input before generation, while `:1814-1818` validates generated output and `:2021-2022` emits it unchanged.
- Frontend `[...slug].astro:24-25` renders collection content and has a `set:html` fallback.
- `PostLayout.astro:76-117` and `Breadcrumbs.astro:13-50` use raw JSON strings in inline scripts.
- Existing backend test pattern: `tests/unit/editorial/test_generated_article_guardrails.py`.
- Existing frontend article browser pattern: `tests/playwright/article-rendering.test.ts`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend guardrails | `.venv/bin/python -m pytest tests/unit/editorial/test_generated_article_guardrails.py -q` | all pass |
| Backend lint | `.venv/bin/python -m ruff check news_collector/components/editorial/ai_editor.py tests/unit/editorial/test_generated_article_guardrails.py` | exit 0 |
| Frontend tests | `cd ../noticiencias && npm run test:audit` | all pass |
| Frontend checks | `cd ../noticiencias && npm run lint && npm run validate:content` | exit 0 |
| Build verification | `cd ../noticiencias && npm run build && npm run test:dist` | exit 0; no source diff from generated manifest |

## Scope

**In scope**: backend generated-output validation/tests; frontend JSON-LD serializer and its two article-controlled consumers; a content validation check and security fixtures.

**Out of scope**: sanitizing trusted template configuration, redesigning CSP, supporting arbitrary embeds, changing article prose, or broad replacement of every historical `set:html` call.

## Git workflow

- Matching branches: `advisor/022-safe-published-content`
- Commit examples: `fix(security): reject executable generated markdown`; `fix(security): escape inline json-ld data`.

## Steps

### Step 1: Characterize legitimate raw HTML

Scan current published Markdown/MDX and deterministic editorial fixtures for raw tags, event attributes, and dangerous URL schemes. Record any legitimate syntax and the trusted source that requires it.

**Verify**: a checked-in test fixture or test table documents every allowed case; no production article is silently rewritten.

### Step 2: Reject executable output at the publication boundary

Extend `validate_generated_article_markdown` to reject script-capable elements (`script`, `iframe`, `object`, `embed`, executable SVG/MathML), inline event handlers, `javascript:` URLs, and MDX/JSX expressions. Prefer rejecting generated raw HTML entirely if step 1 finds no legitimate need. Raise `GeneratedArticleValidationError` with a stable security error code; do not sanitize into a different article silently.

**Verify**: focused tests cover mixed case, whitespace/encoding variants, closing tags, event attributes, URI schemes, and safe Markdown.

### Step 3: Add the frontend fail-closed check

Add a content validation script that applies the same documented policy to every post so manually edited or compromised content cannot bypass the backend. Wire it into `lint` and `validate:content` once, avoiding duplicate execution in a combined CI target later.

**Verify**: a malicious temporary fixture fails with a named error and a safe post passes.

### Step 4: Centralize script-safe JSON serialization

Create a narrow `src/utils/json-ld.ts` helper used by both `PostLayout.astro` and `Breadcrumbs.astro`. Serialize JSON and escape at least `<`, `>`, `&`, U+2028, and U+2029 to Unicode escapes before `set:html`. Do not HTML-escape into invalid JSON.

**Verify**: unit tests parse the output as JSON and prove `</script>`, U+2028, and U+2029 never appear literally.

## Test plan

- Backend generated-Markdown tests for safe prose and executable HTML/MDX/URI/attribute encoding variants.
- Frontend content-validator fixtures proving manual posts cannot bypass the same policy.
- JSON-LD round-trip and script-breakout tests for article and breadcrumb payloads.
- Full frontend lint/content/build/dist plus representative article browser smoke.

## Done criteria

- [ ] Generated executable HTML/MDX is rejected before file publication.
- [ ] Frontend content validation independently enforces the policy.
- [ ] Article and breadcrumb JSON-LD use one script-safe serializer.
- [ ] Malicious fixtures are inert/rejected and valid JSON-LD remains parseable.
- [ ] Full backend focused and frontend validation/build gates pass.

## STOP conditions

- Stop if current legitimate content requires arbitrary executable embeds; report exact files and propose a reviewed allowlist rather than weakening the gate globally.
- Stop if a sanitizer dependency would rewrite article meaning or source attribution.
- Stop if build changes the derivative manifest unexpectedly; separate and review that diff before continuing.

## Maintenance notes

Any new inline structured-data block must use the shared serializer. Any intentional embed format needs an explicit allowlist entry, source justification, and regression test in both publication gates.
