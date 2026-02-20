Module: news_collector/logic/workflows/refinery_engine.py
Role: Orchestrates the refinement pipeline to process articles using an editor agent and write them to a target repository.
Inputs:
- article: Dict[str, Any]
- articles: List[Dict[str, Any]]
- target_dir: Path
- target_repo_obj: Any
Outputs:
- Dict[str, Any]
- RefineryEngine
- bool
Side effects:
- Logging
- Network I/O
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
- ValueError
- e
- ve
Used by:
- None
