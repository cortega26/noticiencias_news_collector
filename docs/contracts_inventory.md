## Implemented Contracts (D1 Phase 1)

All boundaries below are now typed and enforced.

### 1. Collector Output

- **Contract**: `CollectorArticleModel` (`contracts/collector.py`)
- **Status**: **Enforced**. `MockArticle` updated to comply with defaults.

### 2. Validation Input

- **Contract**: `ArticleValidationPayload` (`contracts/validation.py`)
- **Status**: **Enforced**. System uses `adapt_to_validation_payload`.

### 3. Scoring Input/Output

- **Input**: `ScoringInputModel` (`contracts/scoring.py`)
- **Output**: `ScoringRequestModel` (`contracts/scoring.py`)
- **Status**: **Enforced**. System uses `adapt_to_scoring_input`.

### 4. Export Payload

- **Contract**: `ExportContractV1` (`contracts/export.py`)
- **Status**: **Enforced**. System uses `adapt_article_to_export`.

## Reference

See `tests/unit/contracts/test_contracts.py` for usage examples.

- **Current State**: Mixed. `BaseCollector` uses `CollectorArticleModel` (Pydantic) in `_filter_and_save_articles`, but some validation logic (`_validate_article_data`) still operates on raw dicts.
- **Payload**:
  - `title`, `url`, `content`, `summary`, `source_id`...
  - `article_metadata` (Dict)
- **Proposed Contract**: `CollectorArticleModel` (Existing in `contracts/collector.py`).
- **Gap**: Enforce usage in `_validate_article_data` and specific collector implementations.

## 2. Validation Input

- **Current State**: Implicit. `_execute_validation` creates a list of dicts manually from ORM objects (`to_dict()`) and injects `content`.
- **shape**:
  - `to_dict()` + `content`
- **Proposed Contract**: `ArticleValidationPayload` (New).
  - Should match the shape expected by `ContentValidator`.
- **Gap**: Validator currently expects raw dicts.

## 3. Scoring Input/Output

- **Input**: List of dicts constructed in `_execute_scoring` from ORM objects.
  - Fields: `id`, `title`, `content`, `summary`, `article_metadata`...
- **Output**: `ScoringRequestModel` (Existing in `contracts/scoring.py`).
  - Used by `FeatureBasedScorer`.
- **Gap**: The input to the scorer is an ad-hoc dict. We should define `ScoringInputPayload`.

## 4. Export Payload (Boundary)

- **Current State**: Ad-hoc dict construction in `export_latest_articles`.
  - `schema_version`, `generated_at`, `contract`, `articles` (List).
- **Proposed Contract**: `ExportContractV1` (New).
  - `version`: Literal["1.0"]
  - `articles`: List[ExportArticleModel]
- **Gap**: Completely missing. Logic is buried in `system/__init__.py`.

## 5. Proposed Action Plan (Phase 1-3)

1.  **ExportContractV1**: Create `contracts/export.py` to define the export schema strictly.
2.  **ScoringInput**: Create `contracts/scoring.py::ScoringInputModel` to standardize what the scorer needs.
3.  **Adoption**: Refactor `_execute_*` methods in `system/__init__.py` to use these models immediately instead of constructing dicts.

This will strictly type the boundaries of the system pipeline.
