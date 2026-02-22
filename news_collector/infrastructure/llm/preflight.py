"""CLI entrypoint for Ollama model preflight checks."""

from news_collector.infrastructure.llm.model_registry import main

if __name__ == "__main__":
    raise SystemExit(main())
