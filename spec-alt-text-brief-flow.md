# Spec — alt-text brief flow (`missing_alt_text`)

## Problem

Articles whose source image ships no usable alt get a pipeline boilerplate
alt, survive ~6 min of LLM stages, then die at frontend lint
(`check-image-alt`). Dead end: no supported path supplies a human alt
(brief reasons only cover missing images; DB metadata doesn't flow).

## Design (fail fast + human owns alt text)

1. Contract: `ImageBriefReason += "missing_alt_text"` (additive only).
2. `image_handler` path 2 (downloaded source image): if the resolved alt is
   boilerplate (`editorial.hero_alt.is_boilerplate_alt`), look for an
   alt-brief for the article with a descriptive `draft_alt_text`.
   - Found → publish with downloaded URL + brief alt (no upload needed).
   - Missing/unusable → queue brief (`missing_alt_text`) and fail the run
     with an actionable message (Images desk → brief slug → write alt →
     retry). No LLM stages burn.
3. `ImageResolution.message` (new, defaulted): carries the actionable
   failure into the run error the desk shows.
4. Images desk: zero changes (queue lists briefs; PUT edits
   `draft_alt_text`; reason renders raw).

## Acceptance

- Boilerplate alt + usable alt-brief → resolves with brief alt.
- Boilerplate alt + no brief → brief queued, run fails with message naming
  the slug; retry after PUT alt → resolves (live proof: article 2422 → PR).
- Good source alt → unchanged (no brief queued).
- Brief with boilerplate alt → treated unusable (no self-accepting loop).
- Contract/validation suites + full unit green; `make lint`.

## Verification

- New unit tests (contract, handler ×4, message surfacing).
- Live: 2422 retry #1 queues brief; PUT coral alt; retry #2 opens the PR.
