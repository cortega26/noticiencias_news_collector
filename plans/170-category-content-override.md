# Plan 170: Content-aware category override for broad source labels

> **Executor instructions**: Follow this plan step by step. Run every verification
> and confirm the expected result. Stop on STOP conditions; do not improvise.
>
> **Drift check**: `git diff --stat f7b4c2e2..HEAD -- news_collector/editorial/categories.py news_collector/editorial/category_resolver.py tests/unit/editorial/`

## Status

- **Priority**: P2 (user-visible misclassification)
- **Effort**: S-M
- **Risk**: LOW (pure rule; false positives are the main risk)
- **Depends on**: none
- **Category**: taxonomy / editorial
- **Planned at**: commit `f7b4c2e2`, 2026-10-19

## Why this matters

Article #3724 (Neanderthal spear wound, archaeology) was published under
**Tecnología**. Cause: `news_collector/config/sources.yaml:235` declares
`media_404.category: technology`; `EditorialCategoryResolver.resolve_category`
maps a non-generic source category **directly** to the public category and
returns before the content classifier runs. The LLM classifier only runs as a
fallback when the source category is generic/missing/unmapped. So the outlet's
label overrode the article's actual domain. The same will happen to every
archaeology/paleontology story from a tech outlet.

The live post was corrected to **Arqueología** in frontend PR #313. This plan
prevents recurrence for future articles without paying for an LLM call on every
article.

## Current state

- `news_collector/editorial/categories.py` — `CANONICAL_PUBLIC_CATEGORIES`
  includes `ARQUEOLOGÍA`; `DIRECT_CATEGORY_MAP` maps
  `technology/tech/... → TECNOLOGÍA` and `archaeology/arqueologia/human_evolution → ARQUEOLOGÍA`.
- `news_collector/editorial/category_resolver.py` — the direct-map branch
  returns immediately for a non-generic source category;
  `resolution_method="direct"`. The classifier fallback branch logs
  `"Category classifier fallback"` and is only reached otherwise.
- `news_collector/config/sources.yaml:230-235` — `media_404` with
  `category: technology`.
- The published post (`categories: [Arqueología]`) is fixed in PR #313; the
  backend export/DB for 3724 still says `technology` until a re-collect/refine.

## Design

Add a **small, curated content override** that runs **before** the direct-map
return, only when the source category is a **broad** label:

- Broad labels: `technology`, `tech` (the only labels where a wrong domain is
  plausible and high-impact today). `science` is already generic → classifier
  fallback; leave it.
- Domain: archaeology (the concrete case). Signals, case/accent-insensitive,
  matched against `title + summary + content[:2000]`:
  - strong: `arqueolog`, `paleoantrop`, `paleontolog`, `neandertal`,
    `homínid`/`hominid`, `prehistori`
  - supporting: `yacimiento`, `excavaci`, `fósil`/`fosil`, `cueva`,
    `entierro`, `restos óseos`, `esqueleto`, `hominino`
- Require **at least two distinct signal groups** (strong counts as one,
  supporting as one) to avoid `fossil fuels` or a stray word.
- If matched: return `ARQUEOLOGÍA` with
  `resolution_method="content_override"` and log article id + matched signals
  (no content).
- Otherwise: existing behaviour exactly.

Keep the rule table data-driven (a small module-level mapping) so future
domains can be added with tests, but do **not** add unproven domains now.

## Scope

**In scope**: `news_collector/editorial/categories.py`,
`news_collector/editorial/category_resolver.py`, `tests/unit/editorial/`
(category resolver tests), `news_collector/taxonomy/README.md` (one paragraph).

**Out of scope**: source configs (do not change 404 Media's label), the LLM
classifier, the frontend, the published post (done in #313), the export/DB
backfill.

## Steps

1. Add the signal tables + a pure `detect_content_category(...)` helper
   (returns a canonical category or `None`) in `categories.py`; unit-test it
   directly.
2. In `resolve_category`, after computing `selected_normalized` and before the
   direct-map return, call the override only when `selected_normalized` is a
   broad label; on a hit return the overridden category with
   `resolution_method="content_override"` (keep the existing fields populated).
3. Tests (table-driven):
   - the 3724 title/summary → `ARQUEOLOGÍA` with `content_override`;
   - a genuine tech article ("OpenAI launches…") with source `technology` →
     `TECNOLOGÍA` (direct);
   - "fossil fuels" + `technology` → `TECNOLOGÍA` (one signal only);
   - source `archaeology` → `ARQUEOLOGÍA` (direct, unchanged);
   - source absent/generic → classifier fallback unchanged (mock the LLM);
   - first-party editorial source unaffected.
4. Docs: one paragraph in `news_collector/taxonomy/README.md` explaining the
   broad-source override and how to add a domain safely.
5. Gates: `make lint`, `make type` (committed), `make test`,
   `make test-contracts`, `make test-boundaries`, `make docs-check`,
   `make inventory-refresh && make inventory-check`, `make plans-ledger-check`.

## Done criteria

- [ ] 3724-like inputs resolve to Arqueología; tech articles stay Tecnología
- [ ] Override only for broad source labels; direct maps and classifier fallback unchanged
- [ ] Tests cover the false-positive cases (fossil fuels, stray word)
- [ ] Pure helper tested; resolver logging names the matched signals
- [ ] Gates green; diff limited to the in-scope files
- [ ] Ledger row 170 updated by the reviewer

## STOP conditions

- The classifier already resolves this correctly in a way the resolver bypasses
  (then fix the ordering instead of adding keywords — report).
- The override would change behaviour for first-party/editorial sources or when
  the source category is already specific → STOP.
- The signal list needs more than ~12 terms or a domain outside archaeology →
  STOP and propose a separate, evidence-backed rule.
- Any publisher/contract change is needed (it is not).

## Maintenance notes

- This is a **narrow** override, not a general content classifier. If more
  domains are added, each needs positive and negative fixtures.
- A re-collect/refine of an existing article is required to update its stored
  category; the frontend post is the publication source of truth.
