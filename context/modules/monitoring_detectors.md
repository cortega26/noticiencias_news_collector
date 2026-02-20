Module: news_collector/monitoring/detectors.py
Role: Implements anomaly detectors for source health, schema drift, and content shifts.
Inputs:
- alert_ratio: float
- articles_found: int
- baselines: Mapping[str, SourceBaseline]
- consecutive_failure_threshold: int
- consecutive_failures: int
- expected_articles_per_window: float
- expected_count: int
- language_distribution
Outputs:
- ContentShiftDetector
- ContentShiftThresholds
- Dict[str, List]
- Mapping[str, float]
- SchemaDriftDetector
- SchemaExpectation
- SourceBaseline
- SourceOutageDetector
Side effects:
- None explicit
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- None explicit
Used by:
- reporting
- io
- canary
