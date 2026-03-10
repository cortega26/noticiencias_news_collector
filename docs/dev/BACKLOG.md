# Backlog (Non-Critical Tech Debt)

## Tech Debt

- [ ] **Config Consolidation**: `apps/refinery` uses its own `.env`. Merge into central `config.toml`.
- [ ] **Model Deduplication**: `CollectorArticleModel` (Pydantic) and `Article` (SQLAlchemy) share 90% fields but drift. Use `sqlmodel` or automated mapping.
- [ ] **Scorer Redundancy**: `PreScorer` (used in collectors) overlaps with `BasicScorer` (used in system). Unify into `ScoringService`.
- [ ] **Logging Standardization**: Some modules use `logging.getLogger`, others use `NewsCollectorLogger` wrapper. Unify.
- [x] **Dependency Audit**: `requirements.txt` lists `pandas` and `streamlit` but they are only for auxiliary tools. Move to `dev` dependencies.

## Wishlist

- [ ] **Mutation Testing**: Re-enable `mutmut` (present in pyproject.toml) to find weak tests.
- [ ] **Contract Tests**: Add schema generation for the scraping output to ensure downstream consumers (Refinery) don't break.
- [ ] **FastAPI Migration**: `serving/` module is barebones. Migrate to a proper `routers/` structure.
