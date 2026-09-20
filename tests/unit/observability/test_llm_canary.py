from news_collector.observability.llm_canary import (
    CanaryThresholds,
    evaluate,
    format_verdict,
)


def test_all_llm_passes():
    v = evaluate({"scoring.llm": 20}, 30.0)
    assert v.ok and v.llm_ratio == 1.0 and not v.reasons


def test_low_ratio_fails_and_names_main_reason():
    v = evaluate(
        {
            "scoring.llm": 5,
            "scoring.heuristic.chunk_failed": 10,
            "scoring.heuristic.budget_exhausted": 5,
        },
        10.0,
    )
    assert not v.ok
    assert "25%" in v.reasons[0] and "chunk_failed" in v.reasons[0]
    assert v.heuristic == 15


def test_threshold_boundary_is_inclusive():
    v = evaluate({"scoring.llm": 16, "scoring.heuristic.chunk_failed": 4}, 1.0)
    assert v.ok  # exactly 80 %


def test_too_slow_fails_even_if_all_llm():
    v = evaluate({"scoring.llm": 20}, 200.0, CanaryThresholds(max_seconds=120))
    assert not v.ok and "200s" in v.reasons[0]


def test_nothing_scored_fails():
    v = evaluate({}, 1.0)
    assert not v.ok and v.reasons == ["no items were scored"]


def test_cached_and_other_stages_are_ignored():
    v = evaluate(
        {"scoring.cached": 50, "rescoring.heuristic.x": 9, "scoring.llm": 4}, 1
    )
    assert v.total == 4 and v.ok


def test_format_verdict_mentions_status_and_reasons():
    ok = format_verdict(evaluate({"scoring.llm": 2}, 1.0))
    bad = format_verdict(evaluate({"scoring.heuristic.chunk_failed": 2}, 1.0))
    assert "CANARY OK" in ok
    assert "FAILED" in bad and "chunk_failed=2" in bad


def _load_script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "scripts" / "llm_canary.py"
    spec = importlib.util.spec_from_file_location("llm_canary_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_skips_without_llm_and_require_keys_fails(monkeypatch, capsys):
    mod = _load_script()
    monkeypatch.setattr(mod, "_llm_configured", lambda: False)
    assert mod.main([]) == 0
    assert "SKIPPED" in capsys.readouterr().out
    assert mod.main(["--require-keys"]) == 2


def test_script_exit_code_follows_verdict(monkeypatch, capsys):
    mod = _load_script()
    monkeypatch.setattr(mod, "_llm_configured", lambda: True)
    monkeypatch.setattr(
        mod, "run_canary", lambda items, th: evaluate({"scoring.llm": items}, 1.0, th)
    )
    assert mod.main(["--items", "3"]) == 0
    monkeypatch.setattr(
        mod,
        "run_canary",
        lambda items, th: evaluate({"scoring.heuristic.chunk_failed": items}, 1.0, th),
    )
    assert mod.main([]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_synthetic_articles_are_distinct():
    mod = _load_script()
    arts = mod.synthetic_articles(7)
    assert len({a.id for a in arts}) == 7 and len({a.title for a in arts}) == 7


def test_canary_payloads_keep_content_via_production_adapter():
    from news_collector.contracts.adapters import adapt_to_scoring_input

    mod = _load_script()
    payload = adapt_to_scoring_input(mod.synthetic_articles(1)[0], None).model_dump()
    assert "Un equipo internacional" in str(payload)
