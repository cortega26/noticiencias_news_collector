# Plan 084 — Vision-model hero alt text

Status: TODO (spec only — not implemented)
Origin: Codex P2 on frontend PR #153 ("Describe the infographic in its alt
text"). Plan 079 and `editorial/hero_alt.py` deliberately deferred the real
fix: today the pipeline only de-anglicises a boilerplate string
(`Ilustración editorial relacionada con {título}`); it never describes the
image. Screen-reader users get nothing of a chart, diagram, or infographic.

## Problem

`ArticleImageHandler.resolve()` sets `image_alt` from an editorial brief's
`draft_alt_text` when one is staged, otherwise a boilerplate placeholder.
`resolve_hero_alt_text()` (frontmatter assembly) swaps a boilerplate/empty
alt for the Spanish-title boilerplate. No stage produces a description of
what the image actually shows. For AI-illustrated heroes and for
source-provided infographics (e.g. the GlucoFM figure: glucose timelines,
a two-stream architecture, a radar comparison, a response forecast) the
published `image_alt` conveys none of the content, failing WCAG 1.1.1 for
complex images.

## Goal / acceptance criteria

1. When the resolved hero image is a local file and the current alt is
   empty or boilerplate (`hero_alt.is_boilerplate_alt`), a multimodal model
   produces a 1–3 sentence Spanish description of the image's principal
   content (subject, and for charts/diagrams: what is compared or shown).
2. A human-written editorial brief `draft_alt_text` always wins — the model
   never overrides a real description.
3. Deterministic, fail-open: any model/network/parse failure logs a warning
   and falls back to today's behaviour (Spanish-title boilerplate). Never
   blocks publication.
4. Cached by image content hash so regenerating an article does not re-bill
   the call; the cache is invalidated when the image bytes change.
5. Off by default; enabled per-environment via config
   (`editorial.vision_alt.enabled`), with an explicit model + timeout +
   monthly-call budget guard, mirroring the Stage 2c fact-check verifier's
   opt-in shape.
6. `check-image-alt` / `check-hero-images` (frontend) and
   `check-editorial-fields` stay green on the full corpus; no backfill of
   existing posts.

## Design sketch

### `infrastructure/llm/gemini_provider.py` (MODIFY)

Add `describe_image_sync(image_bytes, mime_type, prompt) -> str` that posts
a `contents[].parts` payload with an `inline_data` part
(`{mime_type, data: base64(image_bytes)}`) alongside the text prompt, reusing
the existing rate-limiter, circuit-breaker, redaction, and retry paths.
`gemini-2.5-flash` is multimodal; no new dependency. NVIDIA/Ollama providers
raise `NotImplementedError` for now (vision is Gemini-only until a second
provider is needed).

### `editorial/vision_alt.py` (CREATE — policy module, network-free except the injected provider)

- `should_describe(current_alt, brief_alt) -> bool` — true only when
  `brief_alt` is absent/boilerplate and `current_alt` is absent/boilerplate.
- `build_prompt(spanish_title, categories) -> str` — instructs: Spanish, 1–3
  sentences, lead with the image type (foto / ilustración / infografía /
  gráfico), name what a chart compares, no "imagen de" / "ilustración
  editorial relacionada con" prefix, ≤ ~600 chars, no invented data values.
- `describe_hero_image(*, image_path, spanish_title, categories, brief_alt,
  current_alt, provider, cache) -> str | None` — the orchestrator: gate,
  cache lookup by `sha256(image_bytes)`, call `provider.describe_image_sync`,
  validate (non-empty, not boilerplate-prefixed, length), cache, return.
  Returns `None` (caller keeps its current value) on any miss/failure.

### Wiring

Call `describe_hero_image` from `ArticleImageHandler.resolve()` right after a
local image path is known (cases 1–3), OR from the `resolve_hero_alt_text`
call site in `ai_editor.py` frontmatter assembly once `final_title` (Spanish)
exists. Prefer the frontmatter-assembly site: the Spanish title is
guaranteed there, it is where boilerplate is already recomputed, and the
image file is on disk by then. `resolve_hero_alt_text` gains an optional
`describe_fn` parameter (dependency-injected, defaulting to `None` = today's
behaviour) so the policy module stays free of provider imports.

### Cache

`data/runtime/vision_alt/<sha256>.json` (`{alt, model, created_at}`), same
directory convention as other runtime artefacts. Keyed by image bytes, so a
re-download of an unchanged source image or an article retry is free.

## Verification

- Unit: `should_describe` matrix; `build_prompt` contains the constraints;
  `describe_hero_image` — cache hit skips the provider, provider exception →
  `None`, boilerplate-prefixed model output rejected → `None`, happy path
  caches and returns.
- Provider: a deterministic payload-construction test (the `inline_data`
  part is well-formed base64 with the right mime type) + one opt-in live
  test behind an env flag, mirroring `test_fact_check_verification`'s live
  Ollama test.
- Integration: a fixture PNG + boilerplate alt ⇒ frontmatter `image_alt` is
  the model description; a staged brief `draft_alt_text` ⇒ untouched.
- `make lint && make type && make test`; frontend `check:image-alt`,
  `check:hero-images` unaffected on the corpus.

## Non-goals

- Regenerating alt for already-published posts (no backfill).
- Vision for NVIDIA/Ollama providers.
- Generating the hero image itself (that is the editorial brief flow).
- Frontend changes — it already renders whatever `image_alt` contains.

## Cost / risk notes

- One `gemini-2.5-flash` multimodal call per newly-published article whose
  alt is boilerplate. At current publish volume (single digits/day) this is
  negligible, but the config budget guard exists so a backfill or a burst
  cannot run unbounded.
- The model can still write a poor description. `draft_alt_text` from a human
  brief remains the escape hatch, and the fail-open path means a rejected
  output is never worse than today.
