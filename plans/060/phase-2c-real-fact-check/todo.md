# Plan 060 / Phase 2c todo: Real fact-checking against the original source

Execution index for [`spec.md`](spec.md). **spec.md is binding; do not
implement from this checklist alone.** All open design questions from
spec.md's earlier drafts (content threading safety, Stage 4 cache
interaction, cross-lingual comparison, status-overwrite semantics) are
already resolved in spec.md itself — implement exactly what it says, not
what seems reasonable.

Reconciliation with the rest of Plan 060: this phase does not block on, and
is not blocked by, Phase 2b's still-open items (operator's own `reviewed:
true` pass, Phase 2b Step 4's unconditional `STRICT_EDITORIAL` enforcement,
Step 5's cross-repo smoke check) — see spec.md's header. It also does not
touch Phases 4-11, which remain unplanned and untouched.

## Step 0 — baseline

- [ ] `make test` and `make type` pass on `main` before any change (confirm
      the starting point is actually green; do not assume from a prior
      session's memory).
- [ ] Confirm Ollama is reachable and `fact_check_model`'s intended value
      (default: whatever `[ollama] editor_model` currently resolves to) is
      pulled locally (`curl http://localhost:11434/api/tags` or
      equivalent) — do not write code against a model that isn't actually
      available in this environment.

## Step 1 — thread `content` through (spec.md Design §1)

- [ ] No structural change needed — `content` (original-language source,
      `ai_editor.py:1693`/`1704`/`1726`, last reassigned at
      `ai_editor.py:1752`) already survives untouched to the Stage 4
      convergence point (`ai_editor.py:2022`). Confirm this is still true
      at implementation time with a fresh read of
      `process_article` (line numbers may have drifted since this spec was
      written) — do not just trust the line numbers cited here.
- [ ] If a fresh read finds `content` IS reassigned or shadowed somewhere
      between Stage 1 and Stage 4 that this spec's trace missed — stop,
      do not paper over it with a workaround, report back with the exact
      line and re-open the STOP condition spec.md removed.

## Step 2 — new verification method + prompt (spec.md Design §2)

- [ ] Add `fact_check_verification` prompt key to `config/prompts.yaml`.
      Must explicitly:
      - instruct `confirmed`/`uncertain`/`disputed` only (no six-value
        vocabulary leakage from the existing `enrichment` prompt),
      - instruct the model not to invent support for a claim the source
        doesn't address,
      - state plainly when `content_mode` is `summary_only`/
        `summary_fallback` that the provided text is a summary, not the
        full article,
      - **state explicitly that `source_content` may be in a different
        language than the claim, and instruct comparing meaning across
        languages, not surface text.**
      Do NOT modify the existing `enrichment.system` prompt key.
- [ ] Add `_verify_fact_check_claims(claims, source_content, article_title, content_mode) -> list[dict]` to `EditorAgent`.
      Every claim's `status` is overwritten unconditionally — no partial
      pass-through of Stage 4's self-assessed value, ever (see spec.md
      Design §2's explicit rule and §3's failure-handling rule).
- [ ] Add `[ollama] fact_check_model` config key (default: reuse
      `editor_model`'s value), following the exact pattern already used
      for `translator_model`/`editor_model`/`headlines_model`/
      `enrichment_model` in `EditorAgent.__init__`.
- [ ] Construct a dedicated `OllamaProvider` instance for this in
      `EditorAgent.__init__`, separate from `self.provider` (the
      NVIDIA-primary fallback chain used for drafting).
- [ ] Call `_verify_fact_check_claims` from `process_article` at the Stage
      4 convergence point (`ai_editor.py:2022`, after both the cache-hit
      and cache-miss branches produce `enrichment_fields`, before "3.
      Assemble Final Artifact") — **not** inside either branch, and
      **not** conditioned on which branch ran. This must execute on every
      `process_article` call, cache hit or miss.

## Step 3 — failure handling (spec.md Design §3)

- [ ] Ollama call error (timeout/connection refused/malformed response)
      for a given claim → that claim's status is set to `uncertain`
      (never `disputed`, never silently `confirmed`, never left at
      whatever value it had before this step ran).
- [ ] Only a verifier-returned `disputed` reaches the gate in Step 4 below.

## Step 4 — new gate (spec.md Design §4)

- [ ] At the same point Stage 4's existing completeness check runs
      (`ai_editor.py:2178-2189` at spec-writing time — re-confirm at
      implementation time), add: if any verified `fact_check` item has
      `status == "disputed"`, raise `GeneratedArticleValidationError` with
      `error_code="editorial_fact_check_disputed"`, before any
      writer/Git side effect.
- [ ] Error message names which claim(s) were disputed (operator log
      visibility).

## Step 5 — tests

- [ ] Unit: confirmed/uncertain/disputed verification paths.
- [ ] Unit: `summary_only`/`summary_fallback` labeling reaches the prompt.
- [ ] Unit: infrastructure error on a claim → `uncertain`, not a crash, not
      `disputed`, not `confirmed`.
- [ ] Unit: gate raises on any `disputed`, does not raise on
      all-confirmed/uncertain.
- [ ] Unit: a claim Stage 4 self-assessed as `disputed` (old six-value
      vocabulary) that the verifier successfully re-checks as `confirmed`
      does NOT block — proves the overwrite-all rule, not partial
      pass-through.
- [ ] **Unit: a real English-source-text / Spanish-claim fixture** (not a
      same-language synthetic pair) — proves cross-lingual comparison
      actually works, since production input is always cross-lingual.
- [ ] **Unit: Stage 4 cache-hit path still triggers verification** — seed
      a `stage4_enrichment` cache file with an old-style self-assessed
      `fact_check` status, run `process_article`, confirm the verifier
      still runs and can still overwrite/block. Proves the cache-poisoning
      fix in spec.md Design §2.
- [ ] Integration: a `disputed` verdict through the full
      `process_article` call blocks before any writer/Git call.
- [ ] `make test` and `make type` green.

## Step 6 — close out

- [ ] `plans/060/todo.md` updated: add a line noting Phase 2c exists,
      status, and that it does not block Phase 2's remaining items
      (`reviewed: true` pass, Step 4 unconditional enforcement, Step 5
      cross-repo check).
- [ ] `plans/README.md` ledger updated with Phase 2c's completion.
- [ ] This file fully checked off.
