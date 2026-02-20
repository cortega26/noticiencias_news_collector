Module: news_collector/system/pipeline.py
Role: Encapsulates the execution orchestration logic of the full news collection cycle.
Inputs:
- None explicit
Outputs:
- None explicit
Side effects:
- None explicit
Invariants:
- LAW-3: System Layer Is Orchestration Only
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
- RuntimeError
Used by:
- None
