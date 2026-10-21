# Typed contract inventory

Maintained against `news_collector/contracts/`; updated for plan 190 (2026-10-21).
Every `*.py` module in that package is listed below. `make docs-check` fails when a
module is added, removed or renamed without updating this file.

For contract shapes and failure semantics, see
[`docs/PIPELINE_CONTRACTS.md`](PIPELINE_CONTRACTS.md).

## Implemented contracts

### 1. Collector output

- **Module**: `contracts/collector.py`
- **Contracts**: `CollectorArticlePayload`, `CollectorArticleModel`
- **Status**: Enforced. `MockArticle` conforms to required defaults.
- **Tests**: `tests/test_refinery_contract_enforcement.py`,
  `tests/unit/contracts/test_contracts.py`

### 2. Mock article

- **Module**: `contracts/mock_article.py`
- **Contracts**: `MockArticle` (`CollectorArticleModel` subclass)
- **Status**: Enforced. Used by tests to build valid collector payloads.
- **Tests**: `tests/unit/contracts/test_mock_usage.py`

### 3. Common metadata

- **Module**: `contracts/common.py`
- **Contracts**: `ArticleMetadata`, `ArticleMetadataModel`
- **Status**: Enforced. Shared article metadata shape.
- **Tests**: `tests/unit/contracts/test_common_contract.py`,
  `tests/contracts/test_article_model.py`

### 4. Validation input

- **Module**: `contracts/validation.py`
- **Contracts**: `ArticleValidationItem`, `ArticleValidationPayload`
- **Status**: Enforced. System uses `adapt_to_validation_payload`.
- **Tests**: `tests/unit/contracts/test_d1_enforcement.py`,
  `tests/unit/system/test_d1_pipeline_boundaries.py`

### 5. Scoring input/output

- **Module**: `contracts/scoring.py`
- **Contracts**: `ScoringComponents`, `ScoringComponentsModel`, `ScoringRequest`,
  `ScoringRequestModel`, `ArticleScoringData`, `ScoringInputModel`
- **Status**: Enforced. System uses `adapt_to_scoring_input`.
- **Tests**: `tests/contracts/test_scoring_models.py`,
  `tests/unit/contracts/test_contracts.py`

### 6. Enrichment

- **Module**: `contracts/enrichment.py`
- **Contracts**: `ArticleForEnrichment`, `ArticleEnrichment`,
  `ArticleForEnrichmentModel`, `ArticleEnrichmentModel`
- **Status**: Enforced. Models forbid unknown fields and require usable text.
- **Tests**: `tests/unit/contracts/test_enrichment_contract.py`,
  `tests/unit/contracts/test_boundary_contract_extras_rejected.py`

### 7. Export payload

- **Module**: `contracts/export.py`
- **Contracts**: `ExportArticleModel`, `ExportContractV2`
- **Status**: Enforced. System uses `adapt_article_to_export`. `schema_version: 2` is
  the preferred contract; the CLI `--export-json` currently writes V1, tolerated by
  `apps/refinery/main.py` with compatibility handling. New contract work should use V2;
  do not claim that every current producer emits it.
- **Tests**: `tests/unit/contracts/test_export_contract.py`,
  `tests/unit/system/test_d1_pipeline_boundaries.py`

### 8. Frontend publication schema

- **Module**: `contracts/frontend_schema.py`
- **Contracts**: `AstroPost`, `HeadlinesVariants`, `FactCheckItem`, `SourceRole`,
  `EvidenceSubjectType`, `PublicationStatus`, `SourceItem`, `GlossaryItem`,
  `ImageObject`, `SocialConfig`
- **Status**: Enforced. Published MDX frontmatter must satisfy `AstroPost`. The Python
  parity test compares field names; the frontend checker invoked by backend CI also
  checks types, constraints and optionality. See [`docs/PIPELINE_CONTRACTS.md`](PIPELINE_CONTRACTS.md)
  for ownership and intentional divergences.
- **Tests**: `tests/test_contracts_sync.py`,
  `tests/unit/contracts/test_frontend_schema.py`

### 9. Frontend publication policy

- **Module**: `contracts/frontend_publication.py`
- **Contracts**: `FRONTEND_REQUIRED_PUBLICATION_WORKFLOWS` (constant tuple; no models)
- **Status**: Enforced. Shared by the storage projection and the published-content
  reader to identify the workflows that constitute a publication.
- **Tests**: `tests/unit/refinery/test_published_content.py`

### 10. Social publication

- **Module**: `contracts/social_publication.py`
- **Contracts**: functions `derive_social_id`, `apply_social_decision`,
  `stamp_social_frontmatter`; constants `SOCIAL_ID_RE`, `SOCIAL_ID_HASH_PREFIX`
  (no classes)
- **Status**: Enforced. Pure front-matter shape conversion; no I/O or editorial
  decision.
- **Tests**: `tests/unit/contracts/test_social_publication.py`,
  `tests/decompose_refinery/test_target_repo_writer.py`

### 11. Image briefs

- **Module**: `contracts/image_brief.py`
- **Contracts**: `ImageBriefModel`, `IMAGE_BRIEF_STATUS_VALUES`,
  `IMAGE_BRIEF_REASON_VALUES`, `IMAGE_PROMPT_VERSION`, `ImageGenerationMetadata`
- **Status**: Enforced. Typed sidecar for editorial image tasks, origin and
  optional generation evidence. Asset hashes and dimensions are checked against
  decoded bytes before a staged image can release a waiting publication.
- **Tests**: `tests/unit/logic/workflows/test_image_briefs_security.py`,
  `tests/unit/logic/workflows/test_image_brief_provenance.py`,
  `tests/test_serving_admin_api.py`

### 12. Publication validation and attempts

- **Module**: `contracts/publication_validation.py`
- **Contracts**: `FrontendCheckResult`, `PublicationValidationSummary`,
  `PublicationAttemptStageResult`, `PublicationAttemptSummary`
- **Status**: Enforced. Machine-readable summaries for frontend validation and
  publication attempts.
- **Tests**: `tests/unit/logic/workflows/test_refinery_engine.py`,
  `tests/decompose_refinery/test_target_repo_publication.py`

### 13. Webhook callbacks

- **Module**: `contracts/webhook.py`
- **Contracts**: `PublicationAttemptRef`, `DiagnosticResult`, `FrontendWebhookEvent`,
  `ValidationResultEvent`, `PublishCompleteEvent`; functions `parse_webhook_payload`,
  `extract_deploy_url`, `compute_delivery_key`
- **Status**: Enforced. Validates inbound frontend CI callback payloads and derives
  the delivery idempotency key.
- **Tests**: `tests/test_webhook.py`,
  `tests/unit/contracts/test_webhook_contract.py`,
  `tests/integration/test_webhook_receipts.py`

### 14. Source health

- **Module**: `contracts/source_health.py`
- **Contracts**: `SourceHealthRecord`, `SourceOperationalState`,
  `SourceFailureTaxonomy`
- **Status**: Enforced. Stable record shape for `data/exports/source_health.json`
  (runtime artifact, not versioned).
- **Tests**: `tests/unit/contracts/test_source_health_circuit.py`,
  `tests/test_source_health_schema.py`

### 15. Admin API

- **Module**: `contracts/admin.py`
- **Contracts**: 42 classes for `/v1/admin/*`; primary shapes include
  `AdminArticleListEnvelope`, `AdminArticleDetail`, `AdminSourceHealthEnvelope`,
  `AdminDashboardHealthEnvelope`, `AdminCollectStarted`, `AdminPublishStarted`,
  `AdminWebhookReceiptEnvelope`, `AdminImageQueueEnvelope`, `AdminSourceUpsert`
- **Status**: Enforced. Pydantic models are the source of `apps/admin/openapi.json`;
  the generated admin types are never edited by hand.
- **Tests**: `tests/unit/contracts/test_admin_batch_contract.py`,
  `tests/test_serving_admin_api.py`

### 16. Pipeline E2E

- **Module**: `contracts/pipeline_e2e.py`
- **Contracts**: `PipelineStageSnapshot`, `PipelineE2ERunSummary`
- **Status**: Enforced. Typed summary for deterministic end-to-end pipeline runs.
- **Tests**: exercised through `tests/e2e_pipeline/test_pipeline_e2e.py`

### 17. System configuration overrides

- **Module**: `contracts/system.py`
- **Contracts**: `SystemConfigOverrideModel`
- **Status**: Enforced. Strict shape for overrides passed to
  `NewsCollectorSystem` initialization.
- **Tests**: exercised through `tests/unit/system/test_bootstrap_coverage.py`

### 18. Scoring/validation adapters

- **Module**: `contracts/adapters.py`
- **Contracts**: functions including `adapt_article_to_export`,
  `build_collector_payload`, `adapt_article_to_scoring`, `adapt_to_scoring_input`,
  `adapt_to_validation_payload` (no classes)
- **Status**: Enforced. Adapter-owned mapping for scoring, validation, export and
  collector boundaries.
- **Tests**: `tests/unit/contracts/test_adapter_source_stamping.py`,
  `tests/unit/contracts/test_adapter_collector_payload.py`,
  `tests/unit/contracts/test_boundary_contract_extras_rejected.py`

### 19. Reader reports

- **Module**: `contracts/reader_reports.py`
- **Contracts**: `ReaderReportPayload`, `ReportIdentity`; types
  `ReaderProblemType`, `ReaderReportStatus`, `ReaderResolutionStatus`; function
  `is_noticiencias_host`
- **Status**: Enforced at the boundary. Payload mirrors the frontend Worker's six
  problem types, length caps, `noticiencias.com` host rule and optional email.
  `ReportIdentity` is the read-only resolver's typed outcome (no API yet).
- **Tests**: `tests/unit/contracts/test_reader_reports_contract.py`,
  `tests/unit/logic/workflows/test_reader_reports_resolver.py`

### 20. Media-independent editorial draft

- **Module**: `contracts/editorial_draft.py`
- **Contracts**: `EditorialFrontmatter`, `EditorialDraft`
- **Status**: Enforced. Internal editorial projection preserves publication
  validators while deferring image requirements. A content seal detects nested
  mutation and damaged persisted drafts. Preview Markdown is not publishable;
  final assembly still validates the complete `AstroPost` contract.
- **Tests**: `tests/unit/editorial/test_editorial_draft.py`,
  `tests/unit/logic/workflows/test_editorial_image_wait_resume.py`

### 21. Durable publication checkpoint and item outcome

- **Module**: `contracts/publication_checkpoint.py`
- **Contracts**: `CheckpointIdentity`, `PublicationCheckpoint`,
  `PublicationItemOutcome`
- **Status**: Enforced. Source snapshot, editorial draft, identity, fingerprint,
  image dependency and per-item outcome persist in `workflow_runs.run_metadata`
  through the checkpoint repository. An item rejected before preparation can
  retain a failure outcome without a draft.
- **Tests**: `tests/unit/storage/test_publication_checkpoint_repository.py`,
  `tests/unit/logic/workflows/test_editorial_image_wait_resume.py`

### 22. Publication checkpoint adapter

- **Module**: `contracts/publication_checkpoint_adapters.py`
- **Contracts**: function `publication_item_from_result` (no classes)
- **Status**: Enforced. Converts pipeline results into typed succeeded, failed
  or waiting-for-image evidence; zero PRs with an image wait is not a failure.
- **Tests**: `tests/unit/logic/workflows/test_editorial_image_wait_resume.py`,
  `tests/unit/logic/workflows/test_publication_run_workflow.py`

### 23. Package surface

- **Modules**: `contracts/__init__.py` (re-exports `__all__`), `contracts/_constants.py`
  (`SCHEMA_VERSION`, `MANIFEST_FILENAME`)
- **Status**: Enforced. `__init__` exposes the stable package surface; constants are
  shared by schema-bearing contracts.
- **Tests**: `tests/test_refinery_manifest.py`

## Related boundary shapes outside `contracts/`

### Read API

- **Contract**: `ArticleListParams`, `ArticlesEnvelope`
  (`news_collector/serving/api.py`)
- **Status**: Enforced. Deterministic cursor pagination and validated query parameters.

## Reference

- `tests/test_contracts_sync.py` — contract serialisation and cross-repo field parity tests
- `tests/unit/contracts/` — per-contract unit tests
- `docs/PIPELINE_CONTRACTS.md` — authoritative contract shape and failure semantics
