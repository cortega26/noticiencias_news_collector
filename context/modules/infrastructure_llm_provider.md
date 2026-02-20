Module: news_collector/infrastructure/llm/provider.py
Role: Provides a unified interface for LLM interactions via an Ollama provider.
Inputs:
- json_mode: bool
- model: Optional[str]
- model_name: str
- prompt: str
- stream: bool
- system: Optional[str]
Outputs:
- OllamaProvider
- Union[str, Dict[str, Any], Generator[str, None, None]]
- bool
- list[str]
Side effects:
- Logging
- Network I/O
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
- ValueError
Used by:
- pre_scorer
- cognitive_scorer
- classifier
- council
- ai_editor
- auditor
