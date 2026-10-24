"""Scripted provider I/O for real evidence-first preparation and durable holds."""

import json
from unittest.mock import MagicMock

from news_collector.components.editorial.ai_editor import EditorAgent

ARTICLE_BODY = (
    "El estudio describe una observación limitada y no demuestra causalidad. "
    "La fuente explica el método y sus límites; faltan estudios posteriores. "
) * 12
HEADLINES = {
    "direct": "Una observación que requiere nuevos estudios",
    "question": "¿Qué limita la observación?",
    "benefit": "Los límites de este estudio",
    "excerpt": "La observación descrita tiene límites y requiere estudios posteriores.",
    "tags": ["observacion"],
}
ENRICHMENT = {
    "summary_points": ["Observación limitada", "No prueba causalidad"],
    "glossary": [{"term": "Observación", "definition": "Un registro"}],
    "fact_check": [{"label": "No prueba causalidad", "status": "uncertain"}],
    "why_it_matters": [],
    "confidence": "Limitada",
    "sources": [{"title": "Fuente", "url": "https://example.org/source"}],
}


def _provider_payload(response):
    if isinstance(response, Exception):
        raise response
    return response if isinstance(response, str) else json.dumps(response)


def pipeline_with_provider_responses(
    tmp_path,
    monkeypatch,
    reviews,
    repair_suffix="",
    technical_scores=None,
    headline_reviews=None,
    empty_after_rejection=False,
):
    """Exercise real preparation/repair/gating; replace only provider I/O."""
    monkeypatch.setenv("ENABLE_EDITORIAL_CRITIC", "true")
    agent = EditorAgent("http://example", "model")
    agent.cache_dir = tmp_path / "editor-cache"
    agent.cache_dir.mkdir(exist_ok=True)
    agent.category_resolver._classifier = MagicMock(
        try_classify_article=MagicMock(return_value=None)
    )
    responses = iter(reviews)
    scores = iter(technical_scores) if technical_scores is not None else None
    headline_responses = (
        iter(headline_reviews) if headline_reviews is not None else None
    )
    headline_rejected = False
    agent.recorded_repair_prompts = []
    agent.recorded_technical_scores = []
    suffixes = iter(repair_suffix) if isinstance(repair_suffix, list) else None

    def editor_review():
        return _provider_payload(next(responses))

    def headline_review():
        nonlocal headline_rejected
        if headline_responses is None:
            return json.dumps(
                {"approved": True, "fidelity_pass": True, "sensationalism_pass": True}
            )
        response = next(headline_responses)
        if isinstance(response, dict) and response.get("approved") is False:
            headline_rejected = True
        return _provider_payload(response)

    def headlines():
        if empty_after_rejection and headline_rejected:
            return "{}"
        return json.dumps(HEADLINES)

    def technical_review():
        score = next(scores) if scores is not None else 95
        agent.recorded_technical_scores.append(score)
        return json.dumps(
            {"score": score, "reason": "Spanish complete article", "recoverable": True}
        )

    def send(prompt, system="", **kwargs):
        for stage, response in (
            ("editor_critic", editor_review),
            ("headline_critic", headline_review),
            ("headline", headlines),
            ("enrichment", lambda: json.dumps(ENRICHMENT)),
        ):
            if system.startswith(agent.prompts[stage]["system"]):
                return response()
        if prompt.startswith("Analyze the following text across four criteria"):
            return technical_review()
        if prompt.startswith("La versión anterior fue rechazada"):
            agent.recorded_repair_prompts.append(prompt)
            return ARTICLE_BODY + (
                next(suffixes) if suffixes is not None else repair_suffix
            )
        return ARTICLE_BODY

    agent._send_prompt = send
    agent._send_fact_check_prompt = lambda *args, **kwargs: {"status": "uncertain"}
    article = {
        "id": "hold-one",
        "title": "Una observación limitada",
        "content": ARTICLE_BODY,
        "url": "https://example.org/source",
        "source_name": "Fuente",
        "category": "espacio",
    }
    return agent, article, ARTICLE_BODY
