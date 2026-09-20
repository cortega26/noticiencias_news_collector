#!/usr/bin/env python3
"""Real, bounded LLM canary: score a synthetic batch through the actual chain.

Usage:
    python scripts/llm_canary.py [--items 20] [--min-llm-ratio 0.8]
                                 [--max-seconds 120] [--require-keys]

Run it after any change to the provider chain, scoring or budgets (and before
declaring such a change "resolved"): unit tests use fakes and cannot see
free-tier limits, cascades or budget starvation. Uses a throw-away score cache,
so every item goes to the LLM.

Exit codes: 0 = pass (or skipped: no LLM configured, unless --require-keys),
1 = verdict failed, 2 = skipped with --require-keys.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List
from unittest.mock import patch

from news_collector.observability import llm_run_stats
from news_collector.observability.llm_canary import (
    CanaryThresholds,
    evaluate,
    format_verdict,
)

_TOPICS = [
    ("Nuevo estudio sobre microbiota intestinal y sueño", "microbiota"),
    ("Telescopio detecta agua en atmósfera de exoplaneta", "astronomía"),
    ("Batería de estado sólido triplica la densidad energética", "materiales"),
    ("Hallan fósil de dinosaurio con plumas en Patagonia", "paleontología"),
    ("Terapia génica revierte sordera hereditaria en ensayo clínico", "genética"),
]


def synthetic_articles(n: int) -> List[Any]:
    """Distinct, plausible articles (unique text so nothing is cache-shared)."""
    from news_collector.storage.models import Article

    stamp = int(time.time())
    out = []
    for i in range(n):
        title, topic = _TOPICS[i % len(_TOPICS)]
        out.append(
            Article(
                id=f"canary-{stamp}-{i}",
                url=f"https://canary.invalid/{stamp}/{i}",
                title=f"{title} (#{i})",
                summary=f"Investigadores reportan avances en {topic}. Caso {i}.",
                content=(
                    f"Un equipo internacional publicó resultados en {topic}. "
                    f"Los autores describen el método, la muestra y las "
                    f"limitaciones del trabajo número {i}. " * 6
                ),
                source_id="canary",
                published_date=datetime.now(timezone.utc),
                article_metadata={},
            )
        )
    return out


def _llm_configured() -> bool:
    from news_collector.infrastructure.llm.attempts import provider_name
    from news_collector.infrastructure.llm.factory import get_provider

    chain = get_provider(purpose="probe")
    # Ollama is always last in the chain; only remote providers count as "keys".
    return any(
        provider_name(p) != "ollama" for p in getattr(chain, "providers", [chain])
    )


def run_canary(items: int, thresholds: CanaryThresholds):
    from news_collector.scoring.cognitive_scorer import CognitiveScorer

    with tempfile.TemporaryDirectory() as tmp:
        with patch(
            "news_collector.scoring.cognitive_scorer.CACHE_DB_PATH",
            Path(tmp) / "canary_cache.db",
        ):
            scorer = CognitiveScorer()
            payloads = [
                {"article": a.to_dict(), "source_config": {}}
                for a in synthetic_articles(items)
            ]
            llm_run_stats.reset()
            started = time.monotonic()
            asyncio.run(scorer.score_batch_async(payloads))
            elapsed = time.monotonic() - started
    return evaluate(llm_run_stats.snapshot(), elapsed, thresholds)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--items", type=int, default=20)
    parser.add_argument("--min-llm-ratio", type=float, default=0.8)
    parser.add_argument("--max-seconds", type=float, default=120.0)
    parser.add_argument(
        "--require-keys", action="store_true", help="fail instead of skip without LLM"
    )
    args = parser.parse_args(argv)

    if not _llm_configured():
        print("⏭️  CANARY SKIPPED: no LLM provider configured (missing keys?)")
        return 2 if args.require_keys else 0

    verdict = run_canary(
        args.items, CanaryThresholds(args.min_llm_ratio, args.max_seconds)
    )
    print(format_verdict(verdict))
    return 0 if verdict.ok else 1


if __name__ == "__main__":
    sys.exit(main())
