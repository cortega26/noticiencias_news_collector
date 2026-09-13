# Phase 4 — Final verification and deferred technology decisions

## Delivery verification

Read `spec.md`, `todo.md` and the actual diff. A fresh reviewer checks W1–W5,
A1–A5 and E1–E5 against source/tests/results, including negative evidence.
Do not accept “tests added” as proof they ran or “type generation succeeds” as
proof the app's wire behavior remains compatible.

1. Confirm changes belong to the selected phase allowlists and all new paths are
   documented. Inspect runtime edits, if any, more closely than generated output.
2. Confirm there are no new services, production schema/model/prompt changes,
   publication actions or modifications to unrelated Plan 079 work.
3. Confirm no new `importorskip`, blanket type cast, unconditional success return,
   swallowed subprocess status or generated-file manual repair makes a gate lie.
4. Record each required check once against the final applicable code. Rerun only
   checks affected by later changes or unresolved failures. Full phase commands
   are in their documents; don't run them again solely for a final summary.
5. Verify phase 2's dedicated CI job triggers on its relevant paths and consumes
   committed lockfiles. A local check does not prove a remote CI run passed.
6. Update Plan 060 only for the delivered admin subset. Leave its full contract
   rollout, typed transport and publication schema work pending.
7. Update this plan's status honestly. Archive a completed plan or follow the
   ledger's documented KEEP rule. Do not archive partially delivered work.

**V1 output:** `tests/final-results.md` under this plan, listing acceptance IDs,
file/diff references, command outcomes, resolved versions, review findings and
their disposition, intentional limitations, and rollback guidance. “Not run”
must remain distinct from “passed.” No deployment is required for this program.

## Deferred items — no implementation tasks in this plan

These are decision records for a future explicit task, not instructions to keep
adding libraries after completing the selected work.

| Candidate | Evidence needed before implementation | Smallest useful future experiment | No-go condition |
| --- | --- | --- | --- |
| OpenTelemetry | Inventory existing logger, metrics reporter, persistent enrichment metrics and workflow-stage records; identify one unanswered operational question and who will use the output. | Trace one publication run and its existing stages; use bounded export queues, redact content/credentials, keep IDs on spans rather than metric labels. Measure overhead and exporter outage behavior. | Duplicates existing diagnostics, introduces a backend nobody operates, or exporter failures affect publication. |
| Retraction Watch | Specify DOI normalization, original-paper vs retraction-notice relationships, status freshness, evidence storage, and operator-review behavior. | Offline join of explicitly provided DOI fixtures against a dated dataset snapshot; label `matched`, `no_match`, and `unknown/error` distinctly. | Treats `no_match` as proof of validity, blocks publication by an unapproved policy, or silently treats unavailable data as a clean check. |
| Pagefind | Baseline current Lunr search bytes, latency and Spanish-query relevance; preserve URL state and filters. | Separate frontend branch with 20 predeclared Spanish queries and same corpus; compare repeated 375px/1280px runs. Require no relevance/filter regression and at least 20% improvement in transferred search bytes or median warm-search latency, otherwise retain Lunr. | New search costs more without demonstrated improvement, or route/accessibility behavior regresses. |
| DBOS | Recurring need for step resumption after current lifecycle fixes; reviewed side-effect idempotency/reconciliation design; SQLite-compatible operating model. | Explicitly approved isolated collection-only process-kill experiment; compare recovery and maintenance cost. No publishing. | Requires PostgreSQL against operator policy, duplicates ownership state without a cutover plan, or assumes exactly-once GitHub effects. |
| Sentence Transformers | Labeled cross-language same-story/different-story pairs; measured current dedupe misses and false merges. | Offline suggestions on fixed pairs using a multilingual model; report precision/recall and memory/runtime against existing methods. | Auto-merges related-but-distinct studies, adds a vector service before scale requires it, or lacks reviewed labels. |

The Pagefind threshold is a proposed future adoption criterion, not a measured
improvement. Other thresholds must be set before running their future experiments.

Primary references for future discovery (read again when that work is assigned):

- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/).
- [Crossref Retraction Watch access and relationship fields](https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/).
- [Pagefind installation](https://pagefind.app/docs/) and [Spanish support](https://pagefind.app/docs/multilingual/).
- [DBOS architecture](https://docs.dbos.dev/architecture) and [database choices](https://docs.dbos.dev/python/tutorials/database-connection).
- [Sentence Transformers multilingual models](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html).

Retraction integration would expand an existing Crossref capability, not introduce
Crossref for the first time. DBOS's SQLite support alone does not establish that
it fits this application's durability and deployment requirements.
