#!/usr/bin/env python3
"""Bounded prompt comparison through the real editorial chain, without publication.

Credentials come from the existing process environment. All editorial work/cache
is isolated under the requested output directory. No database, PR or media is
created. Outputs are machine-generated and require recorded human assessment.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--publication-date",
        required=True,
        help="Explicit canonical YYYY-MM-DD for this isolated draft",
    )
    parser.add_argument("--baseline-prompts", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--labels", choices=("both", "baseline", "candidate"), default="both"
    )
    parser.add_argument(
        "--content-mode", choices=("full_text", "summary_only"), default="summary_only"
    )
    parser.add_argument("--max-calls", type=int, default=12, choices=range(1, 25))
    parser.add_argument("--max-seconds", type=int, default=600, choices=range(1, 601))
    args = parser.parse_args()

    from noticiencias.config_manager import load_config

    from news_collector.components.editorial.ai_editor import EditorAgent

    runtime_hash = hashlib.sha256(
        (ROOT / "news_collector/components/editorial/ai_editor.py").read_bytes()
    ).hexdigest()
    source = args.source.read_text(encoding="utf-8")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    calls = 0
    records = []
    active_stage = "initialization"
    old_prompts = yaml.safe_load(args.baseline_prompts.read_text(encoding="utf-8"))
    new_prompts = yaml.safe_load(
        (ROOT / "config/prompts.yaml").read_text(encoding="utf-8")
    )

    def timeout_handler(signum, frame):
        raise TimeoutError("Editorial comparison reached its wall-clock budget")

    signal.signal(signal.SIGALRM, timeout_handler)
    try:
        for label, prompts in (("baseline", old_prompts), ("candidate", new_prompts)):
            if args.labels != "both" and args.labels != label:
                continue
            label_started = time.monotonic()
            label_calls = 0
            signal.alarm(args.max_seconds)
            cfg = load_config()
            cfg.paths.data_dir = str(args.output_dir / label)
            agent = EditorAgent(cfg.ollama.api_url, cfg.ollama.model, config=cfg)
            agent.prompts = prompts
            # Same configured provider order/models; explicit evaluation-only
            # bounds prevent a replay from exhausting an account or hanging.
            for provider in getattr(agent.provider, "providers", [agent.provider]):
                if hasattr(provider, "timeout"):
                    provider.timeout = min(provider.timeout, 60)
                if hasattr(provider, "max_tokens"):
                    provider.max_tokens = min(provider.max_tokens, 4096)
                if hasattr(provider, "max_retries"):
                    provider.max_retries = min(provider.max_retries, 1)
            agent.fact_check_provider.timeout = 30
            agent.fact_check_provider.max_retries = 0

            def bounded(send):
                def run(*call_args, **kwargs):
                    nonlocal calls, label_calls, active_stage
                    if (
                        label_calls >= args.max_calls
                        or time.monotonic() - label_started >= args.max_seconds
                    ):
                        raise TimeoutError("Editorial comparison budget exhausted")
                    calls += 1
                    label_calls += 1
                    system = str(
                        kwargs.get("system")
                        or (call_args[1] if len(call_args) > 1 else "")
                    )
                    active_stage = next(
                        (
                            name
                            for name, prompt in prompts.items()
                            if system.startswith(prompt.get("system", "\0"))
                        ),
                        "technical_critic_or_source_support",
                    )
                    return send(*call_args, **kwargs)

                return run

            agent._send_prompt = bounded(agent._send_prompt)
            agent._send_fact_check_prompt = bounded(agent._send_fact_check_prompt)
            before = calls
            output = None
            error = None
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    draft = agent.prepare_article(
                        {
                            "id": "191",
                            "title": args.title,
                            "content": source,
                            "url": args.source_url,
                            "source_name": "NASA",
                            "category": "espacio",
                            "content_mode": args.content_mode,
                        },
                        override_date=args.publication_date,
                    )
                output = draft.preview_markdown
                (args.output_dir / f"{label}-review-packet.md").write_text(
                    draft.grounding_notes, encoding="utf-8"
                )
            except Exception as exc:
                from news_collector.infrastructure.llm.rate_limiter import (
                    redact_message,
                )

                error = (
                    f"{type(exc).__name__} at {active_stage}: "
                    f"{getattr(exc, 'error_code', 'stage_failure')}: "
                    + redact_message(str(exc))[:400]
                )
                (args.output_dir / f"{label}-review-packet.md").write_text(
                    "# Editorial draft held — human review pending\n\n"
                    f"Source: {args.source_url}\n\n"
                    f"Source SHA-256: {hashlib.sha256(source.encode()).hexdigest()}\n\n"
                    f"Failure: {error}\n\n"
                    "The latest draft remains in the isolated stage cache. "
                    "Known findings require explicit successful revalidation.\n\n"
                    + json.dumps(
                        {"critic_verdict": agent.last_critic_verdict},
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            signal.alarm(0)
            record = {
                "case_id": "source-backed-space",
                "output": output,
                "error": error,
                "provenance": "recorded",
                "metadata": {
                    "model": agent.editor_model,
                    "provider": type(agent.provider).__name__,
                    "source_hash": hashlib.sha256(source.encode()).hexdigest(),
                    "prompt_hash": hashlib.sha256(
                        json.dumps(prompts, sort_keys=True).encode()
                    ).hexdigest(),
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                },
            }
            (args.output_dir / f"{label}.jsonl").write_text(
                json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            records.append(
                {
                    "label": label,
                    "calls": calls - before,
                    "elapsed_seconds": round(time.monotonic() - label_started, 2),
                    "last_stage": active_stage,
                    "error": error,
                    "output_chars": len(output or ""),
                    "critic_verdict": agent.last_critic_verdict,
                    "headline_verdict": getattr(agent, "last_headline_verdict", None),
                    "source_support_verdict": getattr(
                        agent, "last_source_support_verdict", None
                    ),
                    "human_review": {"status": "pending", "reviewer": None},
                }
            )
    finally:
        signal.alarm(0)
    report = {
        "scope": "old/new prompts on current runtime, configured provider chain with bounded evaluation-only token/time limits",
        "max_calls_per_label": args.max_calls,
        "max_seconds_per_label": args.max_seconds,
        "source_content_mode": args.content_mode,
        "evaluation_only_source_check_timeout_seconds": 30,
        "evaluation_only_source_check_retries": 0,
        "runtime_ai_editor_sha256": runtime_hash,
        "calls": calls,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "records": records,
        "human_semantic_acceptance": "pending",
        "production_or_deployment_proof": False,
    }
    (args.output_dir / "chain-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "calls": calls,
                "elapsed_seconds": report["elapsed_seconds"],
                "records": [
                    {
                        "label": r["label"],
                        "error": r["error"],
                        "output_chars": r["output_chars"],
                    }
                    for r in records
                ],
            }
        )
    )
    return 0 if all(r["error"] is None for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
