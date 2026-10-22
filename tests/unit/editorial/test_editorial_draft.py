"""Media-independent preparation, durable replay and sealed draft regressions."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from news_collector.components.editorial.ai_editor import EditorAgent
from news_collector.contracts.editorial_draft import EditorialDraft
from news_collector.contracts.frontend_schema import AstroPost

BODY = (
    "Las raíces reciben nutrientes del suelo gracias a asociaciones con hongos. "
    "Las hifas amplían la superficie de contacto y favorecen el intercambio de "
    "compuestos minerales por carbono producido mediante fotosíntesis. "
    "El trabajo identifica diferencias en los procesos celulares asociados con "
    "esta interacción. Sus resultados proceden de ensayos controlados y todavía "
    "deben contrastarse en condiciones ambientales más diversas. "
) * 4
ENRICHMENT = {
    "summary_points": [
        "Los hongos forman redes de hifas",
        "Las raíces intercambian nutrientes",
    ],
    "glossary": [{"term": "Hifa", "definition": "Filamento que forma un hongo"}],
    "fact_check": [{"label": "Las hifas forman redes", "status": "confirmed"}],
    "why_it_matters": ["Ayuda a entender las asociaciones del suelo"],
    "confidence": "Moderada: ensayo de laboratorio",
    "sources": [{"title": "Estudio", "url": "https://example.org/study"}],
}


def pipeline_agent(tmp_path, monkeypatch):
    """Use real editorial stages; fake only the two LLM transport seams."""
    config = SimpleNamespace(
        paths={"data_dir": str(tmp_path)},
        text_processing=SimpleNamespace(
            min_content_length=80, max_headline_retries=0, critic_score_threshold=70
        ),
    )
    agent = EditorAgent("http://example.invalid", "test-model", config=config)
    agent.prompts = {
        name: {"system": f"STAGE_{name}"}
        for name in ("translator", "editor", "editor_critic", "headline", "enrichment")
    }
    calls = []

    def llm_response(prompt, system=None, model=None):
        calls.append(system)
        if "STAGE_translator" in system or "STAGE_editor\n" in system:
            return BODY
        if "Quality Control Editor" in system:
            return json.dumps({"score": 95, "recoverable": True, "reason": "Correcto"})
        if "STAGE_editor_critic" in system:
            return json.dumps(
                {
                    **{
                        f"{key}_score": 8
                        for key in (
                            "hook",
                            "clarity",
                            "structure",
                            "rigor",
                            "voice",
                            "shareability",
                            "closing",
                        )
                    },
                    "approved": True,
                    "material_claims_supported": True,
                    "recoverable": True,
                    "feedback": "",
                    "value_add_assessment": "substantive",
                }
            )
        if "STAGE_headline" in system:
            return json.dumps(
                {
                    "direct": "Cómo las raíces intercambian nutrientes con los hongos",
                    "question": "¿Qué ocurre entre las raíces y los hongos?",
                    "benefit": "Entender las redes de hifas del suelo",
                    "excerpt": "Un estudio analiza las asociaciones entre las raíces y las redes de hifas.",
                    "tags": ["micorriza"],
                }
            )
        if "STAGE_enrichment" in system:
            return json.dumps(ENRICHMENT)
        raise AssertionError(f"Unexpected LLM stage: {system}")

    monkeypatch.setattr(agent, "_send_prompt", llm_response)
    monkeypatch.setattr(
        agent, "_send_fact_check_prompt", lambda *a, **k: {"status": "confirmed"}
    )
    return agent, calls


def raw_article():
    return {
        "id": "3822",
        "title": "Roots and fungal nutrient exchange",
        "content": BODY,
        "summary": "Root networks",
        "category": "salud",
        "source_id": "source-1",
        "source_name": "Fuente",
        "url": "https://example.org/study",
    }


def test_prepare_without_image_and_replay_need_no_more_llm_work(tmp_path, monkeypatch):
    agent, calls = pipeline_agent(tmp_path, monkeypatch)
    draft = agent.prepare_article(raw_article(), override_date="2026-03-02")
    assert draft.critic_verdict["approved"] is True
    assert draft.critic_verdict["average"] == 8.0
    assert "image" not in draft.frontmatter
    assert len(calls) >= 5
    call_count = len(calls)

    stored = EditorialDraft.model_validate_json(draft.model_dump_json())
    markdown = agent.assemble_article(
        stored, "/images/roots.webp", "Raíces e hifas", "ai_generated"
    )
    assert len(calls) == call_count
    parsed = yaml.safe_load(markdown.split("---", 2)[1])
    post = AstroPost.model_validate(parsed)
    assert post.date == date(2026, 3, 2)
    assert post.refinery_id == "3822"
    assert post.image_alt == "Ilustración generada con IA: Raíces e hifas"
    assert markdown.count("source_identity:") == 1


def test_legacy_process_article_remains_image_ready_wrapper(tmp_path, monkeypatch):
    agent, _calls = pipeline_agent(tmp_path, monkeypatch)
    markdown = agent.process_article(
        {**raw_article(), "image_url": "/images/roots.webp", "image_alt": "Raíces"},
        override_date="2026-03-02",
    )
    assert (
        AstroPost.model_validate(yaml.safe_load(markdown.split("---", 2)[1])).image
        == "/images/roots.webp"
    )


def test_draft_rejects_nested_mutation_and_persisted_corruption(tmp_path, monkeypatch):
    agent, _ = pipeline_agent(tmp_path, monkeypatch)
    draft = agent.prepare_article(raw_article(), override_date="2026-03-02")
    stored = draft.model_dump(mode="json")
    stored["content"] = "Changed after review"
    with pytest.raises(ValidationError, match="seal does not match"):
        EditorialDraft.model_validate(stored)
    draft.frontmatter["title"] = "Changed after review"
    with pytest.raises(ValueError, match="seal does not match"):
        agent.assemble_article(draft, "/images/roots.webp", "Raíces", "original")


def test_draft_preserves_non_media_cross_field_validators(tmp_path, monkeypatch):
    agent, _ = pipeline_agent(tmp_path, monkeypatch)
    draft = agent.prepare_article(raw_article(), override_date="2026-03-02")
    stored = draft.model_dump(mode="python")
    stored["seal"] = ""
    stored["frontmatter"]["featured"] = True
    with pytest.raises(ValidationError, match="featured_rank is required"):
        EditorialDraft.model_validate(stored)
    stored["frontmatter"]["featured"] = False
    stored["frontmatter"]["image"] = None
    with pytest.raises(ValidationError, match="must not contain media"):
        EditorialDraft.model_validate(stored)


def test_changed_candidate_invalidates_critic_and_enrichment_approvals(
    tmp_path, monkeypatch
):
    from news_collector.components.editorial.editorial_stages import EditorialStage

    agent, calls = pipeline_agent(tmp_path, monkeypatch)
    article = raw_article()
    agent.prepare_article(article, override_date="2026-03-02")
    calls.clear()
    cached_editorial = agent._get_cache_path("3822", EditorialStage.EDITORIAL)
    cached_editorial.write_text(
        BODY.replace("procesos celulares", "procesos biológicos")
    )
    agent.prepare_article(article, override_date="2026-03-02")
    assert any("Quality Control Editor" in call for call in calls)
    assert any("STAGE_editor_critic" in call for call in calls)
    assert any("STAGE_enrichment" in call for call in calls)


def test_disabled_technical_review_cannot_create_success_checkpoint(
    tmp_path, monkeypatch
):
    from news_collector.components.editorial.editorial_stages import EditorialStage

    agent, _ = pipeline_agent(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_TRANSLATION_GUARD", "false")
    draft = agent.prepare_article(raw_article(), override_date="2026-03-02")
    assert not agent._get_cache_path(
        "3822", EditorialStage.TECHNICAL_CRITIC_OK
    ).exists()
    assert agent.last_technical_verdict["verification_status"] == "unverified"
    assert "Revisión técnica" in draft.grounding_notes
