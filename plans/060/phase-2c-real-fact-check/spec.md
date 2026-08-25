# Plan 060 / Phase 2c: Real fact-checking against the original source

> Part of Plan 060. Extends Phase 2's "truthful schema v2 publication" theme.
> Depends on nothing structurally new — reuses Phase 2a's fail-closed
> exception pattern and runs entirely inside the existing `EditorAgent`
> pipeline. Complementary to, not blocking on, Phase 2b's remaining items
> (the operator's own review pass, unconditional `STRICT_EDITORIAL`).

## Why this phase exists

Phase 2b's manual, one-time adversarial audit against the 30-post backlog
found systematic factual errors — including a quote fabricated and
attributed to a real NASA official — that the pipeline's own `fact_check`
field never caught. This phase asks: why not, and is it cheap to fix going
forward, for every future article, without repeating a manual audit each
time.

**Scope, per the operator (2026-08-25):** "fact-check" here means comparing
the final draft against the article's own original source content — nothing
broader. If the original source itself is wrong, that is out of scope; the
job is only to confirm the draft faithfully represents what the cited
source actually says.

## Recon findings (this session, code-verified — see the investigation this
spec is built on for exact file:line references)

**The root cause is a missing input, not a missing capability.** The
original-language source text is already persisted on every `Article` row
(`content` column, `models.py`) — fetched during collection, used once as
Stage 1 translation input in `EditorAgent.process_article`
(`ai_editor.py:1754-1783`), then never referenced again in that function.
`_generate_enrichment_fields` (`ai_editor.py:1355-1429`, "Stage 4" — the
function that writes `fact_check`) only ever receives the *final Spanish
draft*, truncated to 4000 chars (`_sample_for_critic`, `ai_editor.py:1387`).
Its own docstring says it "analyzes the final edited article." It has never
had access to the source it's supposedly checking against. This is why the
existing `fact_check` field is a self-consistency check, not a
verification: a model checking its own paraphrase against itself will
confirm almost anything, including a fabricated quote.

**The existing "auditor" is a different concern, not a fact-checker.**
`EditorialAuditor.audit_article_sync` (`auditor.py:277-343`) scores tone,
epistemic rigor, and speculation control on the Spanish draft. It receives
`source_url` only as a label string (`auditor.py:333`) — never fetches or
compares against it. `_enforce_editorial_policy`
(`refinery_engine.py:955-1017`) gates on the auditor's score, non-blocking
by default. Nothing in the current pipeline reads source content a second
time after Stage 1 translation.

**A genuinely independent model is already configured and running.**
`config.toml`'s `[ollama]` section already names
`editor_model = "qwen3-next:80b-a3b-instruct-q4_K_M"` — a different model
family from the NVIDIA Nemotron model (`nvidia/nemotron-3-super-120b-a12b`)
that drafts articles in production. Ollama is reachable locally
(confirmed live, 2026-08-25). `OllamaProvider` (`provider.py:52`) can be
constructed directly with an explicit model, independent of
`get_provider()`'s NVIDIA-primary `FallbackProvider` chain — no new
provider infrastructure is needed to route a specific call through a
specific, different model.

**The existing fail-closed pattern is directly reusable.**
`GeneratedArticleValidationError` (`ai_editor.py:228-234`) with
`error_code="editorial_v2_incomplete"` already blocks publication before
writer/Git side effects when Stage 4 output is incomplete
(`ai_editor.py:2183-2189`, inside `process_article`, right after Stage 4
fields are merged into `model_dict`). The new fact-check gate is another
check at the same point, with a new `error_code`, using the same exception
class — not a new mechanism.

**`content_mode` matters for what "the source" even means.** Of 781
articles in the real dev DB: 582 `full_text`, 194 `summary_only`, 5
`summary_fallback` (`models.py:161-163`; queried directly, not assumed).
For the ~25% of the corpus collected as `summary_only`, the stored
`content` is itself a summary, not the full original article — the
verifier can only catch errors visible within that summary.

**Existing fact_check status vocabulary is wider than needed for a
verification gate.** The current enrichment prompt (`config/prompts.yaml`,
`enrichment.system`) instructs the model to self-assign one of six status
values: `confirmed`, `uncertain`, `disputed`, `exaggerated`, `misleading`,
`needs_review`. The new verification step (below) uses a focused
three-value vocabulary instead — `confirmed` / `uncertain` / `disputed` —
matching exactly what the Phase 2b adversarial audit already used
(VERIFIED/UNSUPPORTED/CONTRADICTED), to keep the new gate's semantics
unambiguous rather than inheriting six overlapping categories.

## Operator decisions (2026-08-25)

- **Fits under Plan 060 as Phase 2c.** Plan 060's spec.md lists "rewriting
  editorial prompts/policy while extracting stages" as out of scope — read
  as guarding Wave C's stage-extraction refactor from picking up unrelated
  prompt changes, not a blanket ban on ever touching editorial prompts in
  this program (Phase 2a already established precedent: it added a
  fail-closed gate, which is itself a policy change).
- **Verifier runs on a different model than the drafter** — Ollama
  `qwen3-next`, not the NVIDIA model that wrote the draft. Reduces the risk
  of the verifier sharing the same blind spots as the writer.
- **Blocks publication only on `disputed`** (the verifier's real
  comparison found the claim contradicts the source). `uncertain`
  (verifier couldn't confirm from the available source) is advisory only —
  recorded in the published `fact_check` field, not a publish blocker.
  Rationale: blocking on "couldn't verify" too would likely reject articles
  that are fine but whose source just didn't happen to state something
  explicitly — a real false-positive risk with a single-source, no-fetch
  design.
- **`summary_only`/`summary_fallback` articles are fact-checked against the
  stored summary as-is** — no live fetch of `source_url` added. Weaker
  verification for that ~25% of the corpus, but keeps this phase's scope
  to "compare against what we already have," with zero new network
  dependency or failure mode on the publish path.

## Design

### 1. Thread the original source content through (verified safe — no
restructuring needed)

`EditorAgent.process_article` holds the original-language `content` in a
local variable set once (`ai_editor.py:1693`/`1704`/`1726`) and last
reassigned at `content = clean_html(content)` (`ai_editor.py:1752`). Traced
every line referencing `content` from there through the end of
`process_article` (line-by-line read, not assumed): it is never reassigned
again. All of the critic/repair re-entry loops (Stage 1.5, 2.5, 2.6, 3.5)
read and write a *different* variable, `final_content` (the translated/
edited Spanish draft) — they never touch `content`. So `content` survives
untouched, unconditionally, to the Stage 4 call site regardless of how many
repair/critic cycles run. No restructuring is needed; the original STOP
condition about this is resolved and removed. Capture it in a
same-named local at the top of the function (it already exists) — nothing
else changes.

### 2. New verification call — always runs, cache-hit or cache-miss alike

**Cache hazard, verified in code and designed around:** `process_article`'s
Stage 4 block (`ai_editor.py:1965-2021`) has two paths — cache hit
(`cached_enrichment` reused as-is, `_generate_enrichment_fields` never
called) and cache miss (`_generate_enrichment_fields` called, result
written to `cache_s4`). Both paths converge into the same `enrichment_fields`
variable immediately before the "3. Assemble Final Artifact" comment
(`ai_editor.py:2023`). **If the new verification call were placed only
"immediately after `_generate_enrichment_fields` returns" (as an earlier
draft of this spec said), it would silently never run on any cache hit** —
and every article reprocessed from a pre-existing `stage4_enrichment` cache
file (including every article cached before this phase ships) would keep
its old six-value self-assessed `fact_check` statuses forever, since
`fact_check` is itself one of the `_V2_REQUIRED_ENRICHMENT_FIELDS`
(`ai_editor.py:218-225`) that makes a cache "usable" — a self-assessed
`disputed`/`confirmed` value is non-empty, so it passes that check and is
never regenerated. The gate would then no-op on nearly every real run.

**Fix:** the new verification call is placed once, unconditionally, at
`ai_editor.py:2022` — after both cache branches converge into
`enrichment_fields`, before assembly — not inside either branch. It runs
every single time `process_article` executes, whether Stage 4 came from
cache or was freshly generated. Verification itself is not cached; it is
cheap enough (one small prompt per claim, local Ollama) that re-running it
on a cache hit is the correct tradeoff over risking silent staleness.

Add a new private method
`_verify_fact_check_claims(claims: list[dict], source_content: str, article_title: str, content_mode: str) -> list[dict]`,
called from `process_article` at that convergence point. It:

- Takes the `fact_check` claims Stage 4 already drafted (unchanged —
  `_generate_enrichment_fields` itself is not modified; it still drafts
  `summary_points`/`glossary`/`fact_check` labels/`why_it_matters`/
  `confidence`/`sources` exactly as today).
- Sends each claim's `label` plus `source_content` to a **new, small,
  dedicated prompt** (add a new top-level key in `config/prompts.yaml`,
  e.g. `fact_check_verification`) modeled directly on the adversarial audit
  prompt's instructions: compare the claim against the source, output
  `confirmed`/`uncertain`/`disputed`, do not invent support for a claim the
  source doesn't address. If `content_mode` is `summary_only`/
  `summary_fallback`, the prompt says plainly that the provided text is a
  summary, not the full article, so the model doesn't overclaim confidence
  either way. **The prompt must say explicitly that `source_content` may be
  in a different language than the claim** (the stored source is typically
  English; claims are always Spanish, since they're drafted from the
  translated article) — this is cross-lingual claim verification, not a
  same-language diff, and the prompt needs to instruct the model to compare
  meaning across languages, not surface text.
- **Overwrites every claim's `status` unconditionally** with this
  verification result — all claims, always, no partial pass-through. The
  six-value self-assessment from Stage 4 (including any self-assessed
  `disputed`) is fully discarded; nothing from the old vocabulary can reach
  the new gate. This closes the gap where a self-assessed `disputed` the
  verifier never even looked at could otherwise trigger a block on a
  verdict this phase explicitly doesn't trust.
- Runs on a dedicated `OllamaProvider` instance, constructed once in
  `EditorAgent.__init__` alongside the existing provider setup, using a new
  `[ollama] fact_check_model` config key (default: reuse
  `editor_model`'s value, following the existing per-stage model config
  pattern already used for `translator_model`/`editor_model`/
  `headlines_model`/`enrichment_model`) — not the `self.provider` used for
  drafting.

### 3. Failure handling — fail open on infrastructure errors, fail closed only on a real "disputed" verdict

Matches this codebase's existing precedent exactly:
`_generate_enrichment_fields` itself "falls back to empty defaults so
enrichment never blocks publication" on validation/LLM errors
(`ai_editor.py:1377-1379`). The new verification step follows the same
philosophy in the opposite direction — bad *content* blocks, bad
*infrastructure* does not:

- If the Ollama call errors (timeout, connection refused, malformed
  response) for a given claim, **set** that claim's status to `uncertain`
  (not `disputed`, not silently `confirmed`, and not left at whatever
  Stage 4 self-assessed) and log it. Per the rule above, every claim's
  status is always overwritten by this step — on an infra error the
  overwrite is to `uncertain`, never a pass-through of the old value. A
  flaky local Ollama instance must not become a hard dependency for all v2
  publication.
- Only a claim the verifier actually returned as `disputed` triggers the
  block below.

### 4. New fail-closed gate — reuses the existing exception, not a new mechanism

In `process_article`, at the same point Stage 4's field-completeness check
already runs (`ai_editor.py:2178-2189`), add: if any verified `fact_check`
item has `status == "disputed"`, raise `GeneratedArticleValidationError`
with a new `error_code="editorial_fact_check_disputed"`, before the
writer/Git side effects `frontend_publication_validation.py` already
documents this class of gate as blocking. Message should name which
claim(s) were disputed, for operator visibility in logs.

## Scope boundaries

**In scope:**
- Threading `content` into the new verification call.
- The new `_verify_fact_check_claims` method and its dedicated prompt.
- A dedicated Ollama provider instance and `fact_check_model` config key.
- The new fail-closed gate on `disputed` status, reusing
  `GeneratedArticleValidationError`.
- Tests: unit tests for the new method (confirmed/uncertain/disputed
  paths, `summary_only` labeling, infrastructure-error → `uncertain`
  fallback, the new gate raising/not-raising), **at least one test using a
  real English-source-text / Spanish-claim fixture** (not a same-language
  synthetic pair — the production input is always cross-lingual, so a
  Spanish-only fixture would pass while proving nothing about real
  behavior), a test confirming the gate raises with a `confirmed` claim
  paired with a self-assessed-`disputed`-but-never-verified claim
  discarded correctly (proves the overwrite-all rule, not partial
  pass-through), a test that a Stage 4 **cache hit** still runs
  verification (proves the cache-poisoning fix), and an integration-level
  test through `process_article` confirming a `disputed` claim blocks
  before any writer/Git call.

**Out of scope (do not touch):**
- `_generate_enrichment_fields`'s own prompt/logic — it keeps drafting
  `fact_check` labels and the other five fields exactly as today; only the
  `status` field gets overwritten by the new verification step.
- The existing `EditorialAuditor` (tone/rigor/speculation scoring) —
  unrelated concern, not modified.
- Fetching `source_url` live for `summary_only` sources — explicitly
  deferred per the operator's decision above.
- Re-running verification against the 30-post backlog this session already
  hand-corrected (Phase 2b) — this phase is about future articles; the
  backlog's resolution stands as already recorded in
  `phase-2b-corpus-cutover/review/step2-review-outcomes.md`.
- Any change to the `EnrichmentSchema`/`FactCheckItem` Pydantic models —
  `status` is already a free-form `str` on both backend and frontend
  contracts; no schema change needed for the narrower three-value
  vocabulary.

## STOP conditions

- If `qwen3-next` (or whatever `fact_check_model` resolves to) proves
  unreliable enough in practice that most claims fall back to `uncertain`
  on infrastructure errors rather than getting a real verdict — stop and
  report the failure rate rather than silently shipping a gate that never
  actually fires.
- If a source's `content` is empty/null even though `content_mode` claims
  otherwise (a data-quality edge case not yet observed) — treat as
  verification-unavailable (all claims `uncertain`), do not guess.

## Done criteria

- [ ] New v2 articles get `fact_check` statuses assigned by a real
      comparison against the article's own stored source content, not
      self-assessment against the model's own draft.
- [ ] The verification call runs on a different model than the one that
      drafted the article.
- [ ] A `disputed` verdict blocks publication before writer/Git side
      effects, using the existing `GeneratedArticleValidationError`
      pattern; `uncertain` does not block.
- [ ] Infrastructure failure in the verification call degrades to
      `uncertain`, never silently to `confirmed` and never itself blocking
      publication.
- [ ] `summary_only`/`summary_fallback` articles are verified against the
      stored summary with an honest "this is a summary" label in the
      prompt context.
- [ ] Verification runs unconditionally after Stage 4 (cache hit or cache
      miss) — a cached article's old self-assessed statuses cannot survive
      to the gate, proven by a cache-hit test.
- [ ] The verifier correctly handles cross-lingual comparison (Spanish
      claim vs. original-language, typically English, source content),
      proven by at least one real English/Spanish fixture, not a
      same-language synthetic pair.
