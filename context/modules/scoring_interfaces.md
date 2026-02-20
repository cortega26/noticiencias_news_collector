Module: news_collector/scoring/interfaces.py
Role: Defines protocol abstractions for asynchronous article scorers.
Inputs:
- None explicit
Outputs:
- AsyncScorer
Side effects:
- None explicit
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- None explicit
Used by:
- feature_scorer
- basic_scorer
