"""Offline replay harness for the LLM routing benchmark.

Re-runs production editorial prompts (translator -> editor -> headlines,
critics) through per-arm provider configurations and records outputs,
judges, latency, and serving attribution. Standalone by design (plan 080
Phase 3 is TODO): no new dependencies, no production behavior changes.

Arms (see spec-llm-routing-benchmark.md):
  A  control   production config (NVIDIA Super primary)
  B  ultra     harness endpoint nvidia-ultra + purpose_chains.editing
  C  glm       harness endpoint zai-glm-flash (reasoning low) + chain
Judges run in a separate phase over recorded outputs:
  production auditor path (default chain) + forced-local reference.

Attribution: per-run rows from data/metrics/<env>/llm_metrics.db
(ts window + purpose='editing'). Any run served by a non-primary model
is MIXED: retried once, then excluded from quality means (but counted in
robustness stats). Failures are never dropped from the denominator.

Isolation: per-arm article ids (bench-<arm>-<dbid>) namespace the editor
file cache and auditor metadata; no DB writes; no publishing.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/llm_routing_replay.py --phase dry-run
  PYTHONPATH=. .venv/bin/python scripts/llm_routing_replay.py --phase generate [--max-cases N]
  PYTHONPATH=. .venv/bin/python scripts/llm_routing_replay.py --phase judge
  PYTHONPATH=. .venv/bin/python scripts/llm_routing_replay.py --phase bundle
  PYTHONPATH=. .venv/bin/python scripts/llm_routing_replay.py --phase analyze
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

EVAL_DIR = REPO_ROOT / "reports" / "evaluation" / "routing"
CASES_PATH = REPO_ROOT / "reports" / "evaluation" / "routing_benchmark_cases.jsonl"
RUNS_PATH = EVAL_DIR / "runs.jsonl"
JUDGMENTS_PATH = EVAL_DIR / "judgments.jsonl"
BUNDLE_PATH = EVAL_DIR / "blind_bundle.md"
MAPPING_PATH = EVAL_DIR / "blind_mapping.sealed.json"
INTERIM_PATH = EVAL_DIR / "interim_automated.md"

ARMS = ("A", "B", "C")
# BENCH_SKIP_ARMS="C" pauses an arm without touching recorded rows
# (used when a host endpoint is down for the whole window: no point
# burning wall-clock on guaranteed failovers; revisit at the end).
SKIP_ARMS = {
    a.strip().upper()
    for a in (os.environ.get("BENCH_SKIP_ARMS", "") or "").split(",")
    if a.strip()
} & set(ARMS)
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
NVIDIA_KEY_ENV = "NOTICIENCIAS__NVIDIA__API_KEY"

ARM_MODEL = {
    "A": "nvidia/nemotron-3-super-120b-a12b",
    "B": "nvidia/nemotron-3-ultra-550b-a55b",
    "C": "z-ai/glm-5.3-flash",
}
ARM_ENDPOINT = {"B": "nvidia-ultra", "C": "zai-glm-flash"}


def _load_config():
    from noticiencias.config_manager import load_config

    return load_config()


def build_arm_config(arm: str, base_cfg):
    """Deep copy of production config with this arm's provider wiring.

    Arm A returns the production config untouched. Arms B/C append a
    harness-only endpoint and pin purpose_chains.editing to it (the
    factory treats purpose chains as an allow-list; unlisted providers
    are dropped, Ollama is always appended last).
    """
    if arm == "A":
        return base_cfg
    from noticiencias.config_schema import LLMEndpointConfig

    cfg = base_cfg.model_copy(deep=True)
    if arm == "B":
        endpoint = LLMEndpointConfig(
            name="nvidia-ultra",
            base_url=NVIDIA_BASE,
            model=ARM_MODEL["B"],
            api_key_env=NVIDIA_KEY_ENV,
            timeout=300,
            max_tokens=32768,
        )
        chain = ["nvidia-ultra"]
    elif arm == "C":
        endpoint = LLMEndpointConfig(
            name="zai-glm-flash",
            base_url=NVIDIA_BASE,
            model=ARM_MODEL["C"],
            api_key_env=NVIDIA_KEY_ENV,
            # 60s, not the editing-standard 300s: the hosted GLM endpoint
            # is timing out wholesale (verified 120s+ on minimal probes
            # 2026-09-21). A healthy endpoint answers in well under a
            # minute; hanging longer only burns wall-clock before the
            # recorded failover. Documented deviation, quality-neutral:
            # it cannot make GLM look better, only fail faster.
            timeout=60,
            max_tokens=32768,
            extra_body={"reasoning_effort": "low", "clear_thinking": True},
        )
        chain = ["zai-glm-flash"]
    else:  # pragma: no cover - argparse restricts arms
        raise ValueError(f"unknown arm {arm!r}")
    cfg = cfg.model_copy(update={"llm_endpoints": [*cfg.llm_endpoints, endpoint]})
    llm = cfg.llm.model_copy(
        update={"purpose_chains": {**cfg.llm.purpose_chains, "editing": chain}}
    )
    return cfg.model_copy(update={"llm": llm})


def arm_fingerprint(arm: str, cfg) -> dict:
    """Provenance recorded with every result row."""
    from news_collector.infrastructure.llm.factory import get_provider

    provider = get_provider(purpose="editing", config=cfg, timeout=60)
    primary = provider.providers[0] if hasattr(provider, "providers") else provider
    return {
        "arm": arm,
        "primary_provider": primary.__class__.__name__,
        "primary_model": getattr(primary, "model", None),
        "primary_endpoint": getattr(primary, "name", None),
        "expected_model": ARM_MODEL[arm],
    }


def _metrics_rows(t0: float, t1: float, environment: str = "development") -> list[dict]:
    db = REPO_ROOT / "data" / "metrics" / environment / "llm_metrics.db"
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in con.execute(
            "SELECT provider, model, ok, kind, latency_ms, failover_index"
            " FROM llm_calls WHERE ts >= ? AND ts <= ? AND purpose = 'editing'"
            " ORDER BY ts",
            (t0, t1 + 1.0),
        )
    ]
    con.close()
    return rows


def _bench_logger():
    from news_collector.utils.logger import get_logger

    return get_logger().create_module_logger("llm-routing-benchmark")


def _load_cases(limit: int | None = None) -> list[dict]:
    cases = [
        json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
    ]
    return cases if limit is None else cases[:limit]


def _case_input(db_id: str) -> dict:
    con = sqlite3.connect(f"file:{REPO_ROOT / 'data' / 'news_v3.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT id, title, summary, content, content_mode, url, source_id,"
        " source_name, category FROM articles WHERE id = ?",
        (int(db_id),),
    ).fetchone()
    con.close()
    if row is None:
        raise ValueError(f"db article {db_id} not found")
    d = dict(row)
    return {
        "id": str(d["id"]),
        "title": d["title"] or "",
        "summary": d["summary"] or "",
        "content": d["content"] or "",
        "content_mode": d["content_mode"] or "full_text",
        "url": d["url"] or "",
        "source_id": d["source_id"] or "",
        "source_name": d["source_name"] or "",
        "category": d.get("category") or "",
    }


MAX_ATTEMPTS = 3


def _run_state(path: Path) -> tuple[dict[tuple[str, str], int], set[tuple[str, str]]]:
    """Prior attempt counts per (db_id, arm), plus keys with an ok row.

    A key needs work when it has no ok row and fewer than MAX_ATTEMPTS.
    Re-invoking generate therefore acts as the revisit pass: cooldowns and
    tripped breakers have cleared, so mixed cases get a fair retry instead
    of an immediate doomed one.
    """
    counts: dict[tuple[str, str], int] = {}
    oks: set[tuple[str, str]] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (rec.get("db_id", ""), rec.get("arm", ""))
            counts[key] = counts.get(key, 0) + 1
            if rec.get("status") == "ok":
                oks.add(key)
    pending = {
        key: n for key, n in counts.items() if key not in oks and n < MAX_ATTEMPTS
    }
    return pending, oks


def cmd_dry_run() -> int:
    """Build all arm configs + resolve primaries. Zero LLM calls."""
    from news_collector.infrastructure.llm.model_registry import (
        resolve_ollama_stage_models,
    )
    from news_collector.utils.logger import get_logger

    base = _load_config()
    for arm in ARMS:
        cfg = build_arm_config(arm, base)
        fp = arm_fingerprint(arm, cfg)
        resolved = resolve_ollama_stage_models(cfg, logger=_bench_logger())
        print(
            json.dumps(
                {**fp, "constructor_default": resolved["default"]}, ensure_ascii=False
            )
        )
        assert (
            fp["primary_model"] == ARM_MODEL[arm]
        ), f"arm {arm}: resolved {fp['primary_model']!r}, expected {ARM_MODEL[arm]!r}"
    print("dry-run OK: all arms resolve to their intended primaries, no calls made")
    return 0


def cmd_generate(max_cases: int | None) -> int:
    import copy as _copy

    from news_collector.components.editorial.ai_editor import (
        EditorAgent,
        validate_generated_article_markdown,
    )
    from news_collector.infrastructure.llm.model_registry import (
        resolve_ollama_stage_models,
    )
    from news_collector.utils.logger import get_logger

    logger = _bench_logger()
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    pending, resolved_ok = _run_state(RUNS_PATH)
    base_cfg = _load_config()
    agents = {}
    for arm in ARMS:
        cfg = build_arm_config(arm, base_cfg)
        resolved = resolve_ollama_stage_models(cfg, logger=logger)
        agents[arm] = (
            EditorAgent(
                api_url=cfg.ollama.api_url,
                model=resolved["default"],
                translator_model=resolved["translator"],
                editor_model=resolved["editor"],
                headlines_model=resolved["headlines"],
                enrichment_model=resolved["enrichment"],
                config=cfg,
            ),
            arm_fingerprint(arm, cfg),
        )

    cases = _load_cases(max_cases)
    with RUNS_PATH.open("a", encoding="utf-8") as out:
        for case in cases:
            payload = _case_input(case["db_id"])
            for arm in ARMS:
                if arm in SKIP_ARMS:
                    continue
                key = (case["db_id"], arm)
                if key in resolved_ok:
                    print(f"skip {key[0]}-{key[1]} (ok recorded)")
                    continue
                prior = pending.get(key, 0)
                if prior >= MAX_ATTEMPTS:
                    continue
                agent, fp = agents[arm]
                attempt = prior + 1
                run_id = f"bench-{arm}-{case['db_id']}" + (
                    "" if attempt == 1 else f"-r{attempt}"
                )
                rec: dict = {
                    "run_id": run_id,
                    "db_id": case["db_id"],
                    "arm": arm,
                    "attempt": attempt,
                    "stratum": case["stratum"],
                    "hard": case["hard"],
                    "fingerprint": fp,
                }
                t0 = time.time()
                try:
                    # Reset: the agent only assigns last_critic_verdict on
                    # judged paths, so a stale verdict from a previous run
                    # would otherwise leak into an abstaining run.
                    agent.last_critic_verdict = None
                    output = agent.process_article(
                        payload,
                        explicit_article_id=run_id,
                        override_date=case.get("canonical_date"),
                    )
                    rec["wall_s"] = round(time.time() - t0, 1)
                    rec["output_chars"] = len(output)
                    rec["output"] = output
                    rec["critic_verdict"] = _copy.deepcopy(agent.last_critic_verdict)
                    try:
                        validate_generated_article_markdown(output)
                        rec["schema_ok"] = True
                        rec["schema_error"] = None
                    except Exception as exc:  # noqa: BLE001 - recorded, not raised
                        rec["schema_ok"] = False
                        rec["schema_error"] = f"{type(exc).__name__}: {exc}"[:300]
                    rows = _metrics_rows(t0, time.time())
                    rec["served"] = rows
                    foreign = [r for r in rows if (r["model"] or "") != ARM_MODEL[arm]]
                    if foreign:
                        rec["status"] = "mixed"
                        rec["mixed_rows"] = foreign
                    else:
                        rec["status"] = "ok"
                except Exception as exc:  # noqa: BLE001 - failures are data
                    rec["wall_s"] = round(time.time() - t0, 1)
                    rec["status"] = "failed"
                    rec["error"] = f"{type(exc).__name__}: {exc}"[:500]
                    rec["served"] = _metrics_rows(t0, time.time())
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                print(
                    f"{run_id}: {rec['status']} "
                    f"({rec.get('wall_s', '?')}s, "
                    f"{len(rec.get('served', []))} calls)"
                )
    return 0


def _extract_body(markdown: str) -> str:
    """Best-effort publishable body for judging (mirrors the spirit of
    validate_generated_article_markdown without duplicating its rules)."""
    text = markdown or ""
    parts = text.split("---")
    if len(parts) >= 3 and not parts[0].strip():
        text = "---".join(parts[2:])
    return text.strip()


def cmd_judge() -> int:
    """Run the production auditor path + forced-local reference over every
    ok run output. Appends to judgments.jsonl (resumable)."""
    from news_collector.components.editorial.auditor import EditorialAuditor

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    if not RUNS_PATH.exists():
        print("no runs.jsonl — run --phase generate first")
        return 2
    runs = [
        json.loads(line) for line in RUNS_PATH.read_text(encoding="utf-8").splitlines()
    ]
    cases = {
        json.loads(line)["db_id"]: json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
    }
    done = set()
    if JUDGMENTS_PATH.exists():
        for line in JUDGMENTS_PATH.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            done.add((rec["run_id"], rec["judge"]))
    prod_cfg = _load_config()
    local_cfg = prod_cfg.model_copy(deep=True)
    local_llm = local_cfg.llm.model_copy(update={"chain": ["ollama"]})
    local_cfg = local_cfg.model_copy(update={"llm": local_llm})
    auditors = {
        "prod": EditorialAuditor(prod_cfg),
        "local": EditorialAuditor(local_cfg),
    }
    with JUDGMENTS_PATH.open("a", encoding="utf-8") as out:
        for run in runs:
            if run.get("status") != "ok" or not run.get("output"):
                continue
            body = _extract_body(run["output"])
            for judge, auditor in auditors.items():
                if (run["run_id"], judge) in done:
                    continue
                jid = f"bench-j-{judge}-{run['run_id']}"
                t0 = time.time()
                try:
                    result = auditor.audit_article_sync(
                        jid,
                        body,
                        cases.get(run["db_id"], {}).get("source_url", ""),
                    )
                    status = "ok"
                    error = None
                except Exception as exc:  # noqa: BLE001 - failures are data
                    result, status, error = None, "failed", str(exc)[:300]
                out.write(
                    json.dumps(
                        {
                            "judgment_id": jid,
                            "run_id": run["run_id"],
                            "db_id": run["db_id"],
                            "arm": run["arm"],
                            "judge": judge,
                            "judge_model": getattr(auditor, "model", None),
                            "status": status,
                            "error": error,
                            "result": result,
                            "wall_s": round(time.time() - t0, 1),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                out.flush()
                print(f"{jid}: {status}")
    return 0


BUNDLE_N = 12
BUNDLE_HARD_N = 4
BUNDLE_SEED = 20260922


def cmd_bundle() -> int:
    """Assemble the blind human-review bundle.

    Only articles with ok runs in ALL THREE arms are eligible. Labels are
    randomly permuted per article; the mapping is sealed in a separate file
    that must stay out of the review bundle.
    """
    import random as _random

    if not RUNS_PATH.exists():
        print("no runs.jsonl — run --phase generate first")
        return 2
    ok: dict[str, dict[str, dict]] = {}
    for line in RUNS_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("status") == "ok" and rec.get("output"):
            ok.setdefault(rec["db_id"], {})[rec["arm"]] = rec
    eligible = [db for db, arms in ok.items() if set(arms) == set(ARMS)]
    cases = {
        json.loads(line)["db_id"]: json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
    }
    hard = [d for d in eligible if cases.get(d, {}).get("hard")]
    easy = [d for d in eligible if not cases.get(d, {}).get("hard")]
    rng = _random.Random(BUNDLE_SEED)
    rng.shuffle(hard)
    rng.shuffle(easy)
    picked = (hard[:BUNDLE_HARD_N] + easy[: BUNDLE_N - BUNDLE_HARD_N])[:BUNDLE_N]
    if len(picked) < BUNDLE_N:
        print(f"only {len(picked)} fully-ok articles; bundle will be short")
    mapping: dict[str, dict] = {}
    bundle = [
        "# Blind review bundle — LLM routing benchmark",
        "",
        "Rank the three texts per item 1st/2nd/3rd for Spanish editorial",
        "voice (curious entry, rigorous method, useful close). Return ranks as",
        'JSON: `[{"item": 1, "first": "B", "second": "A", "third": "C",',
        ' "notes": "..."}, ...]`. Do NOT try to guess which system is which.',
        "",
    ]
    for idx, db_id in enumerate(picked, 1):
        labels = list("ABC")
        rng.shuffle(labels)
        arms = sorted(ok[db_id])
        placement = dict(zip(labels, arms, strict=True))
        mapping[str(idx)] = {
            "db_id": db_id,
            "labels": {
                label: ok[db_id][arm]["run_id"] for label, arm in placement.items()
            },
            "stratum": cases.get(db_id, {}).get("stratum"),
            "hard": cases.get(db_id, {}).get("hard"),
        }
        bundle.append(f"## Item {idx} (stratum: {mapping[str(idx)]['stratum']})")
        bundle.append("")
        for label in sorted(placement):
            arm = placement[label]
            bundle.append(f"### Version {label}")
            bundle.append("")
            bundle.append(_extract_body(ok[db_id][arm]["output"])[:6000])
            bundle.append("")
    BUNDLE_PATH.write_text("\n".join(bundle), encoding="utf-8")
    MAPPING_PATH.write_text(
        json.dumps(
            {"seed": BUNDLE_SEED, "items": mapping}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    print(f"bundle: {len(picked)} items -> {BUNDLE_PATH} (mapping sealed)")
    return 0


def _pct(nums: list[float], pct: float) -> float | None:
    if not nums:
        return None
    ordered = sorted(nums)
    idx = min(len(ordered) - 1, int(pct / 100 * len(ordered)))
    return ordered[idx]


def cmd_analyze() -> int:
    """Automated metrics over runs + judgments (human ranks merged later)."""
    if not RUNS_PATH.exists():
        print("no runs.jsonl — run --phase generate first")
        return 2
    runs = [
        json.loads(line)
        for line in RUNS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("{")
    ]
    judgments: list[dict] = []
    if JUDGMENTS_PATH.exists():
        judgments = [
            json.loads(line)
            for line in JUDGMENTS_PATH.read_text(encoding="utf-8").splitlines()
        ]
    lines = ["# Interim automated metrics — LLM routing benchmark", ""]
    for arm in ARMS:
        arm_runs = [r for r in runs if r.get("arm") == arm]
        ok = [r for r in arm_runs if r.get("status") == "ok"]
        statuses = [r.get("status") for r in arm_runs]
        lines.append(f"## Arm {arm} ({ARM_MODEL[arm]})")
        lines.append(
            f"- runs: {len(arm_runs)} (ok {len(ok)}, "
            f"mixed {statuses.count('mixed')}, failed {statuses.count('failed')})"
        )
        if ok:
            schema = sum(1 for r in ok if r.get("schema_ok")) / len(ok)
            walls = [r["wall_s"] for r in ok if r.get("wall_s") is not None]
            verdicts = [r.get("critic_verdict") for r in ok]
            judged = [v for v in verdicts if isinstance(v, dict)]
            approved = [v for v in judged if v.get("approved")]
            calls = sum(len(r.get("served", [])) for r in ok)
            foreign = sum(
                1
                for r in ok
                for s in r.get("served", [])
                if s.get("failover_index", 0) > 0
            )
            lines.append(
                f"- schema_ok: {schema:.0%}  |  critic: "
                f"{len(approved)} approved / {len(judged)} judged / "
                f"{len(ok)} ok (abstain = critic fail-open, tracked separately)"
            )
            lines.append(
                f"- wall p50/p95: {_pct(walls, 50)}s / {_pct(walls, 95)}s  |  "
                f"llm calls: {calls}  |  failover-served: {foreign}"
            )
        lines.append("")
    for judge in ("prod", "local"):
        recs = [j for j in judgments if j.get("judge") == judge]
        if not recs:
            continue
        lines.append(f"## Judge {judge} ({len(recs)} judgments)")
        for arm in ARMS:
            arm_recs = [j for j in recs if j.get("arm") == arm]
            ok_recs = [j for j in arm_recs if j.get("status") == "ok"]
            lines.append(f"- arm {arm}: {len(ok_recs)}/{len(arm_recs)} ok")
        lines.append("")
    if CROSS_PATH.exists():
        lines.append("## Cross-critic matrix (output-arm x critic-arm approval)")
        cross = [
            json.loads(line)
            for line in CROSS_PATH.read_text(encoding="utf-8").splitlines()
        ]
        header = "out\\critic | " + " | ".join(ARMS) + " |"
        lines.append(header)
        for output_arm in ARMS:
            cells = []
            for critic_arm in ARMS:
                recs = [
                    c
                    for c in cross
                    if c.get("output_arm") == output_arm
                    and c.get("critic_arm") == critic_arm
                    and c.get("status") == "ok"
                ]
                if recs:
                    cells.append(
                        f"{sum(1 for c in recs if c.get('approved'))}/{len(recs)}"
                    )
                else:
                    cells.append("-")
            lines.append(f"{output_arm} | " + " | ".join(cells) + " |")
        lines.append("")
        lines.append(
            "_Diagonal inflation (self-approval >> cross-approval) "
            "means the critic is lenient to its own model; read "
            "output-arm quality down the fixed-critic columns._"
        )
    if GROUNDED_PATH.exists():
        lines.append("## Grounded fact-check (claims vs source content)")
        for arm in ARMS:
            recs = [
                json.loads(line)
                for line in GROUNDED_PATH.read_text(encoding="utf-8").splitlines()
                if json.loads(line).get("arm") == arm
            ]
            ok_recs = [r for r in recs if r.get("status") == "ok"]
            lines.append(
                f"- arm {arm}: {len(ok_recs)}/{len(recs)} judged, "
                f"{sum(r.get('n_claims', 0) for r in ok_recs)} claims total"
            )
        lines.append("")
    lines.append("_Human blind ranks merged separately before thresholds apply._")
    INTERIM_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


CROSS_PATH = EVAL_DIR / "cross_critic.jsonl"
GROUNDED_PATH = EVAL_DIR / "grounded.jsonl"


def _parse_output_frontmatter(markdown: str) -> dict:
    """Frontmatter dict from a generated article ({} when unparseable)."""
    import yaml

    parts = (markdown or "").split("---")
    if len(parts) < 3 or parts[0].strip():
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except Exception:  # noqa: BLE001 - recorded as absent, not raised
        return {}
    return data if isinstance(data, dict) else {}


def _bundle_subset() -> list[dict]:
    """The 12 bundle cases (recomputed identically to cmd_bundle)."""
    import random as _random

    ok: dict[str, set[str]] = {}
    for line in RUNS_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("status") == "ok" and rec.get("output"):
            ok.setdefault(rec["db_id"], set()).add(rec["arm"])
    eligible = [db for db, arms in ok.items() if arms == set(ARMS)]
    cases = {
        json.loads(line)["db_id"]: json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
    }
    hard = sorted(d for d in eligible if cases.get(d, {}).get("hard"))
    easy = sorted(d for d in eligible if not cases.get(d, {}).get("hard"))
    rng = _random.Random(BUNDLE_SEED)
    rng.shuffle(hard)
    rng.shuffle(easy)
    return [
        {"db_id": db, **cases.get(db, {})}
        for db in (hard[:BUNDLE_HARD_N] + easy[: BUNDLE_N - BUNDLE_HARD_N])[:BUNDLE_N]
    ]


def _fixed_critic_agents():
    """One EditorAgent per arm config, used ONLY for critic calls.

    Generation already happened; these agents never draft. Calling the
    critic through arm X's model over every arm's outputs yields the
    full output-arm x critic-arm approval matrix, which separates
    output quality from grader leniency (Codex P1 on PR #322).
    """
    from news_collector.components.editorial.ai_editor import EditorAgent
    from news_collector.infrastructure.llm.model_registry import (
        resolve_ollama_stage_models,
    )

    base_cfg = _load_config()
    agents = {}
    for arm in ARMS:
        cfg = build_arm_config(arm, base_cfg)
        resolved = resolve_ollama_stage_models(cfg, logger=_bench_logger())
        agents[arm] = EditorAgent(
            api_url=cfg.ollama.api_url,
            model=resolved["default"],
            translator_model=resolved["translator"],
            editor_model=resolved["editor"],
            headlines_model=resolved["headlines"],
            enrichment_model=resolved["enrichment"],
            config=cfg,
        )
    return agents


def cmd_cross_critic() -> int:
    """3x3 critic matrix on the bundle subset (post-hoc, no regeneration)."""
    import copy as _copy

    if not RUNS_PATH.exists():
        print("no runs.jsonl — run --phase generate first")
        return 2
    outputs: dict[tuple[str, str], dict] = {}
    for line in RUNS_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("status") == "ok" and rec.get("output"):
            outputs[(rec["db_id"], rec["arm"])] = rec
    subset = _bundle_subset()
    if not subset:
        print("no fully-ok cases yet — run generate first")
        return 2
    agents = _fixed_critic_agents()
    done = set()
    if CROSS_PATH.exists():
        for line in CROSS_PATH.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                done.add((rec["db_id"], rec["output_arm"], rec["critic_arm"]))
            except (json.JSONDecodeError, KeyError):
                continue
    with CROSS_PATH.open("a", encoding="utf-8") as out:
        for case in subset:
            db_id = case["db_id"]
            row = _case_input(db_id)
            for output_arm in ARMS:
                rec = outputs.get((db_id, output_arm))
                if rec is None:
                    continue
                fm = _parse_output_frontmatter(rec["output"])
                body = _extract_body(rec["output"])
                context = {
                    "title": fm.get("title", ""),
                    "summary": fm.get("excerpt", ""),
                    "source_url": row["url"],
                    "source_name": row["source_name"],
                    "category": row.get("category", ""),
                }
                for critic_arm in ARMS:
                    if (db_id, output_arm, critic_arm) in done:
                        continue
                    agent = agents[critic_arm]
                    agent.last_critic_verdict = None
                    t0 = time.time()
                    try:
                        valid, reason, _ = agent._critic_editorial_pass(body, context)
                        verdict = _copy.deepcopy(agent.last_critic_verdict)
                        status, error = "ok", None
                    except Exception as exc:  # noqa: BLE001 - failures are data
                        valid, reason, verdict = None, None, None
                        status, error = "failed", str(exc)[:300]
                    out.write(
                        json.dumps(
                            {
                                "db_id": db_id,
                                "output_arm": output_arm,
                                "critic_arm": critic_arm,
                                "status": status,
                                "error": error,
                                "approved": valid,
                                "reason": (reason or "")[:300],
                                "verdict": verdict,
                                "wall_s": round(time.time() - t0, 1),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    out.flush()
                    print(
                        f"cross {db_id} out={output_arm} critic={critic_arm}: "
                        f"{status} approved={valid}"
                    )
    return 0


def cmd_grounded() -> int:
    """Source-grounded fact-check judging over every ok output (post-hoc).

    Uses each arm's own drafted fact_check labels against the DB source
    content, verified through a dedicated always-Ollama provider — the
    same independence property as production Phase 2c, and the fixed
    grounded judge Codex P1 (PR #322) requires. The production auditor
    never sees source contents, so its counts stay demoted to
    prose-caution flags (spec §6).
    """
    if not RUNS_PATH.exists():
        print("no runs.jsonl — run --phase generate first")
        return 2
    agents = _fixed_critic_agents()
    done = set()
    if GROUNDED_PATH.exists():
        for line in GROUNDED_PATH.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                done.add((rec["db_id"], rec["arm"]))
            except (json.JSONDecodeError, KeyError):
                continue
    with GROUNDED_PATH.open("a", encoding="utf-8") as out:
        for line in RUNS_PATH.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") != "ok" or not rec.get("output"):
                continue
            key = (rec["db_id"], rec["arm"])
            if key in done:
                continue
            row = _case_input(rec["db_id"])
            fm = _parse_output_frontmatter(rec["output"])
            labels = [
                item.get("label")
                for item in (fm.get("fact_check") or [])
                if isinstance(item, dict) and item.get("label")
            ]
            claims = [{"label": label} for label in labels]
            t0 = time.time()
            try:
                verdicts = agents["A"]._verify_fact_check_claims(
                    claims,
                    row["content"] or "",
                    fm.get("title", ""),
                    row.get("content_mode", "full_text"),
                )
                status, error = "ok", None
            except Exception as exc:  # noqa: BLE001 - failures are data
                verdicts, status, error = None, "failed", str(exc)[:300]
            out.write(
                json.dumps(
                    {
                        "run_id": rec["run_id"],
                        "db_id": rec["db_id"],
                        "arm": rec["arm"],
                        "status": status,
                        "error": error,
                        "n_claims": len(claims),
                        "verdicts": verdicts,
                        "wall_s": round(time.time() - t0, 1),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            out.flush()
            print(f"grounded {rec['run_id']}: {status} ({len(claims)} claims)")
            done.add(key)
    return 0
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=[
            "dry-run",
            "generate",
            "judge",
            "cross-critic",
            "grounded",
            "bundle",
            "analyze",
        ],
        required=True,
    )
    parser.add_argument("--max-cases", type=int, default=None)
    args = parser.parse_args(argv)
    if args.phase == "dry-run":
        return cmd_dry_run()
    if args.phase == "generate":
        return cmd_generate(args.max_cases)
    if args.phase == "judge":
        return cmd_judge()
    if args.phase == "cross-critic":
        return cmd_cross_critic()
    if args.phase == "grounded":
        return cmd_grounded()
    if args.phase == "bundle":
        return cmd_bundle()
    if args.phase == "analyze":
        return cmd_analyze()
    return 2


if __name__ == "__main__":
    sys.exit(main())
