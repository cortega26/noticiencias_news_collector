# Roadmap — Plans 085–102 (Fifth Pass, Deep Audit)

**Audit base:** back-end repo `noticiencias_news_collector` @ `e77a039` (2026-09-16).
**Scope:** plans 085–102 only. Prior passes live in `plans/README.md` (ledger) and `plans/archive/`.
**Owner model:** one executor per plan, in an isolated worktree (`execute <NNN>`), advisor reviews the diff.
**Ledger:** `plans/README.md` stays the status source of truth — this file is the *operating view* (order, waves, scoreboard). Executors update the ledger, not this file; the advisor refreshes the scoreboard below on reconcile.

## Go-to in 30 seconds

| I want to… | Go here |
|---|---|
| Pick the next plan to execute | [Wave 0](#wave-0--signal-hygiene-first) (start here) → Waves in order |
| Check overall progress | [Scoreboard](#scoreboard) |
| Know what can run in parallel | [Wave execution rules](#wave-execution-rules) |
| Find a plan file | [Backlog table](#backlog--all-18-plans) |
| Know what's deliberately NOT planned | [Deferred & rejected](#deferred--rejected-do-not-re-audit) |
| Run the gates for any plan | `make lint && make type && make test` + plan-specific extras (each plan file lists them) |
| Validate the ledger after updates | `.venv/bin/python scripts/validate_plans_ledger.py` → must print OK |

## Scoreboard

> Advisor: update on every reconcile. Executors: do NOT edit this — update your `plans/README.md` row.

| Wave | Theme | Plans | Done | Status |
|------|-------|-------|------|--------|
| 0 | Signal hygiene first | 096, 097, 098, 102 | 4/4 | DONE |
| 1 | Serving API correctness (strictly sequential) | 085, 087, 088, 090, 091, 099 | 6/6 | DONE |
| 2 | Identity & publication integrity (strictly sequential) | 089, 094, 093, 086, 100, 095 | 6/6 | DONE (095 partial; remainder → 106) |
| 3 | Collector perf + policy architecture (parallel-safe) | 092, 101 | 1/2 | IN PROGRESS (101 DONE in `d696b51`; 092 STOPped on coverage ratchet, being rescoped) |
| 4 | Log-triage fixes (103+104 parallel-safe, 105 independent) | 103, 104, 105 | 3/3 | DONE |
| **Total** | | **22** | **20/22** | |

**Time-sensitive:** 096 touches the NLTK allowlist entry expiring **2026-09-30** — do not let Wave 0 slip past that date without at least triaging it (the plan handles it; worst case, triage the expiry standalone).

## Wave 0 — Signal hygiene first

*Why first:* these make every later wave verifiable. A lying perf gate (097), an untested quality gate (102), a no-op contributor check (098), and disagreeing audit paths (096) undermine all downstream "green" claims. All are S effort, LOW risk, and touch disjoint areas except the Makefile (see ordering).

| Order | Plan | One-liner | Files touched |
|-------|------|-----------|---------------|
| 0.1 | 098 | Alias `audit-placeholders` to the real gate | `Makefile` (1 target), `CONTRIBUTING.md` |
| 0.2 | 097 | Unmask `make perf` failures | `Makefile` (1 target), `docs/ci.md` |
| 0.3 | 096 | Unify audit exceptions; triage NLTK expiry | `Makefile`, `scripts/security_gate.py`, `SECURITY.md`, lockfiles via sync flow |
| 0.4 | 102 | Quality-gate success + tamper tests | `tests/test_quality_gate.py` only |

**Wave-done check:** `make lint && make docs-check && make security && make quality && make perf` all exit 0 with no masks; `validate_plans_ledger.py` → OK.

## Wave 1 — Serving API correctness (STRICTLY SEQUENTIAL)

*Why grouped:* six plans touch `news_collector/serving/api.py` in different regions. Isolated-worktree executors WILL conflict on this file — run them one at a time, in this order (each merges before the next starts). The order goes contract-first (085 adds a response field others must not break), codec before consumers, filter-set before validation-mapping.

| Order | Plan | One-liner | Region in `api.py` |
|-------|------|-----------|--------------------|
| 1.1 | 085 | Bulk-reset cap reported explicitly | bulk-reset endpoint (~1971–1996) + `contracts/admin.py` + `bulk_helper.py` |
| 1.2 | 087 | Image-brief traversal guard + bounded uploads | image-brief routes (~1830–1887) + `image_briefs.py` |
| 1.3 | 088 | Cursor full-precision encoding | cursor codec (~228–245) |
| 1.4 | 090 | Drop impossible `status=new` | status set (~119–124) |
| 1.5 | 091 | 422 (not 500) for bad public queries | `get_params` (~721–736) |
| 1.6 | 099 | Warn loudly on dev fail-open | verifiers (~585–643) |

**Wave-done check:** `make lint && make type && make test && make test-boundaries && make security` all exit 0; probe the five endpoints (6-id reset, traversal slug, clustered-score paging, `?status=new`, `?page_size=0`) for the new behaviors.

## Wave 2 — Identity & publication integrity (STRICTLY SEQUENTIAL)

*Why grouped:* publication identity is the system's load-bearing invariant (LAW-B5). Order is dependency-driven: normalize the missing-date boundary (089) → unify the extraction implementation (094) → dedupe the downloader (093) → close the untracked-PR hole (086) → externalize manual-ingest policy onto the now-stable identity semantics (100) → decouple the workflow→UI imports last (095, widest blast radius, benefits from all prior stabilization).

| Order | Plan | One-liner | Files touched |
|-------|------|-----------|---------------|
| 2.1 | 089 | Whitespace dates = missing | `publication_identity.py` (`_derive_date` only) |
| 2.2 | 094 | Single slug-extraction implementation | `refinery_engine.py` + `publication_identity.py` |
| 2.3 | 093 | Single image-download implementation | `refinery_engine.py` + `image_handler.py` |
| 2.4 | 086 | Fail closed before untracked PRs | `pr_orchestrator.py` (+ engine only if needed) |
| 2.5 | 100 | Manual-ingest policy to config/shared owner | `manual_ingest.py` + config/policy owner |
| 2.6 | 095 | Workflows stop importing `apps.refinery` | `target_repo_writer.py`, `publication_run_workflow.py`, new module, UI shim |

**Wave-done check:** `make lint && make type && make test && make test-boundaries && make test-refinery && make quality-gate` all exit 0; no identity value for any previously-successful publish may change (each plan carries its own proof — the wave check is the union).

## Wave 3 — Collector perf + policy architecture (PARALLEL-SAFE)

*Why grouped:* disjoint files, no shared state, opposite ends of the stack. These two MAY run concurrently in separate worktrees.

| Plan | One-liner | Files touched | May parallelize with |
|------|-----------|---------------|----------------------|
| 092 | Batch RSS existence checks | `rss_collector.py` (+ 1-line forwarder if missing) | 101 |
| 101 | Explicit config injection into policy constructors | `council.py`, `classifier.py`, `pre_scorer.py`, `contracts/collector.py` + callers | 092 |

**Wave-done check:** `make lint && make type && make test && make test-boundaries && make test-contracts` all exit 0.

## Wave execution rules

1. **Waves run in order 0 → 3.** Wave 0 first (it repairs the signals later waves rely on). Waves 1–3 are mutually independent by files — after Wave 0, they may overlap *across* waves ONLY if different executors touch different files (check the tables; `serving/api.py` belongs to Wave 1 alone).

## Wave 4 — Log-triage fixes (from the 2026-09-16 production-log triage)

| Order | Plan | One-liner | Files touched |
|-------|------|-----------|---------------|
| 4.1 + 4.2 (parallel-safe) | 103 | Critic fail-open on keyless verdicts + headline blank guard | `ai_editor.py` + editorial tests |
| 4.1 + 4.2 (parallel-safe) | 104 | Strip lifecycle metadata before S1 validation | `contracts/adapters.py`, `apps/refinery/main.py` + contract tests |
| 4.3 (independent, anytime) | 105 | Dead `bair_blog` source verdict (probe → fix/disable) | `sources.yaml` only |

**Wave-done check:** `make lint && make type && make test && make test-contracts && make test-boundaries` all exit 0; article 502's shape re-validates; `bair_blog` verdict recorded with probe evidence.
2. **Sequential inside Waves 1 and 2, no exceptions.** Same-file executors in isolated worktrees produce unmergeable diffs. One plan merges → next starts.
3. **Parallel allowed inside Waves 0 and 3** (disjoint files), except 096/097/098 all touch `Makefile` — run those three in the listed sub-order (0.1 → 0.2 → 0.3).
4. **Every plan starts with its Step 0 baseline and drift check.** A red baseline or drifted excerpt is a STOP, not a fix-forward.
5. **Never run `make quality-gate-refresh`** (overwrites committed snapshots — plan 102's STOP conditions say so explicitly).
6. **Merge discipline:** conventional-commit messages, one plan per branch (`advisor/<NNN>-<slug>` in each plan file), ledger row updated on completion, scoreboard refreshed at reconcile.

## Backlog — all 18 plans

| Plan | Title | Pri | Effort | Wave | Status |
|------|-------|-----|--------|------|--------|
| 085 | [Bulk-reset cap reporting](085-bulk-reset-cap-reporting.md) | P1 | S | 1.1 | DONE |
| 086 | [Fail closed before untracked PRs](086-pr-without-tracking.md) | P1 | M | 2.4 | DONE |
| 087 | [Image-brief hardening](087-image-brief-hardening.md) | P1 | S | 1.2 | DONE |
| 088 | [Cursor precision](088-cursor-precision.md) | P2 | S | 1.3 | DONE |
| 089 | [Whitespace dates as missing](089-whitespace-dates.md) | P2 | S | 2.1 | DONE |
| 090 | [Remove status=new](090-remove-status-new.md) | P3 | S | 1.4 | DONE |
| 091 | [Public list 422s](091-public-list-422.md) | P2 | S | 1.5 | DONE |
| 092 | [Batch existence checks](092-batch-existence-check.md) | P2 | S | 3 | TODO |
| 093 | [Dedupe image download](093-dedupe-image-download.md) | P2 | S | 2.3 | DONE |
| 094 | [Unify slug extraction](094-unify-slug-extraction.md) | P2 | S | 2.2 | DONE |
| 095 | [Workflow→UI decoupling](095-workflow-ui-decoupling.md) | P2 | M | 2.6 | DONE-as-partial (Step 3 → 106) |
| 096 | [Audit exception hygiene](096-audit-exception-hygiene.md) | P1 | S | 0.3 | DONE |
| 097 | [Unmask perf failures](097-perf-fail-open.md) | P2 | S | 0.2 | DONE |
| 098 | [audit-placeholders alias](098-audit-placeholders-alias.md) | P3 | S | 0.1 | DONE |
| 099 | [Fail-open warning](099-fail-open-warning.md) | P2 | S | 1.6 | DONE |
| 100 | [Manual-ingest policy](100-manual-ingest-policy.md) | P3 | M | 2.5 | DONE |
| 101 | [Explicit config injection](101-explicit-config-injection.md) | P3 | M | 3 | DONE |
| 102 | [Quality-gate success path](102-quality-gate-success-path.md) | P2 | S | 0.4 | DONE |
| 103 | [Critic fail-open](103-critic-fail-open.md) | P1 | S | 4.1 | DONE |
| 104 | [Lifecycle strip at validation](104-lifecycle-strip-validation.md) | P1 | S | 4.2 | DONE |
| 105 | [bair_blog resolution](105-bair-source-resolution.md) | P2 | S | 4.3 | DONE |
| 106 | [Publication pipeline extraction](106-publication-pipeline.md) | P2 | M | 2.x | TODO |

## Deferred & rejected (do not re-audit)

- **Rejected at vetting:** auth fail-open as vuln (fail-closed since plan 021); `numpy==2.4.1` pin (satisfies `!=2.4.0`); wildcard-CORS as vuln (explicit allowlist + no credentials).
- **Real but unplanned (lower leverage, future waves):** HtmlCollector follow-on SSRF validation · admin-contract unit tests · refinery-engine de-mocking · SQL score histogram · `make type` double-suite cost · 3-file mypy scope · stale `/healthz` doc example · NLTK expiry watch (fold into 096).
- **Direction (maintainer decision, not scheduled):** reader-correction loop · social distribution past Buffer MVP · vision-model hero alt text (plan 084 spec exists) · offline editorial replay (covered by plan 080 Phase 3 — do not duplicate).
- **Wave-0 follow-up (surfaced 2026-09-16, advisor-verified):** `make quality` Bandit leg red pre-existing (11 Lows) vs `quality-ci` HIGH filter — needs its own plan; 096 deliberately excludes it.
- Full journal: `plans/README.md` fifth-pass section + `docs/audits/2026-08-plans-rejected-findings.md` (prior passes).
