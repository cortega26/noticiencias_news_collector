## Implemented Contracts

All boundaries below are typed and enforced.  This inventory reflects the current
implementation state.  For contract shapes and failure semantics, see
[`docs/PIPELINE_CONTRACTS.md`](PIPELINE_CONTRACTS.md).

### 1. Collector Output

- **Contract**: `CollectorArticleModel` (`contracts/collector.py`)
- **Status**: Enforced.  `MockArticle` conforms to required defaults.

### 2. Validation Input

- **Contract**: `ArticleValidationPayload` (`contracts/validation.py`)
- **Status**: Enforced.  System uses `adapt_to_validation_payload`.

### 3. Scoring Input/Output

- **Input**: `ScoringInputModel` (`contracts/scoring.py`)
- **Persistence payload**: `ScoringRequestModel` (`contracts/scoring.py`)
- **Status**: Enforced.  System uses `adapt_to_scoring_input`.

### 4. Export Payload

- **Contract**: `ExportContractV2` (`contracts/export.py`)
- **Status**: Enforced.  System uses `adapt_article_to_export`.  `schema_version: 2` is
  the preferred contract; the CLI `--export-json` currently writes V1, tolerated by
  `apps/refinery/main.py` with compatibility handling. New contract work should use V2;
  do not claim that every current producer emits it.

### 5. Frontend Publication

- **Contract**: `AstroPost` (`contracts/frontend_schema.py`)
- **Status**: Enforced.  Published MDX frontmatter must satisfy `AstroPost`.  The Python parity test compares field names; the frontend checker invoked
  by backend CI also checks types, constraints and optionality. See
  `docs/PIPELINE_CONTRACTS.md` for ownership and intentional divergences.

### 6. Scoring/Validation Adapters

- **Contract**: `news_collector/contracts/adapters.py`
- **Status**: Enforced.  Adapter-owned mapping for scoring and validation boundaries.

### 7. Read API

- **Contract**: `ArticleListParams`, `ArticlesEnvelope` (`news_collector/serving/api.py`)
- **Status**: Enforced.  Deterministic cursor pagination and validated query parameters.

## Reference

- `tests/test_contracts_sync.py` — contract serialisation and cross-repo field parity tests
- `tests/unit/contracts/` — per-contract unit tests
- `docs/PIPELINE_CONTRACTS.md` — authoritative contract shape and failure semantics

