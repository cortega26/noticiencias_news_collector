"""Evidence-first regression behavior; network faked only at provider seams."""

import hashlib
import json
from unittest.mock import MagicMock

import pytest

from news_collector.components.editorial.ai_editor import (
    EditorAgent,
    EnrichmentSchema,
    _parse_editorial_critic_result,
)
from news_collector.editorial.draft_identity import editorial_fingerprint
from news_collector.editorial.evidence_brief import build_evidence_brief
from news_collector.logic.workflows.pr_orchestrator import PROrchestrator


def test_brief_preserves_actual_available_excerpt_and_coverage():
    source = "The detection of a single biosignature by any means does not constitute discovery of life."
    brief = build_evidence_brief(
        title="Biosignatures",
        source_url="https://science.nasa.gov/",
        source_content=source,
        content_mode="summary_only",
    )
    assert brief.passage == source
    assert brief.source_sha256 == hashlib.sha256(source.encode()).hexdigest()
    assert "Solo resumen" in brief.markdown()
    assert "independencia y fuente primaria no verificadas" in brief.markdown()
    assert "pendiente de comprobar" in brief.markdown()


def test_brief_bounds_long_source_and_does_not_fabricate_primary_evidence():
    source = "actual source " * 500
    brief = build_evidence_brief(
        title="Topic", source_url="", source_content=source, content_mode="unknown"
    )
    assert brief.passage == source[:3000]
    assert brief.truncated is True
    assert "URL no disponible" in brief.markdown()
    assert "no asumir texto completo" in brief.markdown()


def _verdict(**changes):
    return {
        **{
            key: 9
            for key in (
                "hook_score",
                "clarity_score",
                "structure_score",
                "rigor_score",
                "voice_score",
                "shareability_score",
                "closing_score",
            )
        },
        "approved": True,
        "recoverable": True,
        "feedback": "",
        "value_add_assessment": "substantive",
        "material_claims_supported": True,
        "support_issues": [],
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {
            "material_claims_supported": False,
            "support_issues": ["Carbon allocation is not permanent storage."],
        },
        {"value_add_assessment": "close_paraphrase"},
    ],
)
def test_material_failure_vetoes_high_scores_and_contradictory_model_approval(changes):
    approved, _, _, average, _ = _parse_editorial_critic_result(_verdict(**changes))
    assert approved is False
    assert average == 9


def test_explicit_limited_evidence_is_not_an_automatic_rejection():
    approved, *_ = _parse_editorial_critic_result(
        _verdict(value_add_assessment="insufficient_source")
    )
    assert approved is True


def test_missing_material_review_stays_unverified_and_cannot_checkpoint():
    agent = object.__new__(EditorAgent)
    agent.prompts = {"editor_critic": {"system": "Review"}}
    agent.editor_model = "model"
    payload = _verdict()
    del payload["material_claims_supported"]
    agent._send_prompt = lambda *a, **k: json.dumps(payload)
    verdict = agent._critic_editorial_pass(
        "Real article body", source_reference="Actual source"
    )
    assert verdict.checkpointable is False
    assert agent.last_critic_verdict["approved"] is False
    assert agent.last_critic_verdict["verification_status"] == "unverified"


def test_no_regional_implication_is_valid_without_inventing_one():
    value = EnrichmentSchema(
        summary_points=["Finding with limits", "Interpretation remains uncertain"],
        glossary=[{"term": "Model", "definition": "A representation"}],
        fact_check=[{"label": "A limited finding", "status": "uncertain"}],
        why_it_matters=[],
        confidence="Limited",
        sources=[{"title": "Source", "url": "https://example.org/source"}],
    )
    assert value.why_it_matters == []


def test_content_source_and_prompt_changes_invalidate_durable_approval():
    article = {"id": 1, "content": "source", "title": "Title", "image_url": "old"}
    settings = {"prompts": {"editor": "faithful"}}
    original = editorial_fingerprint(article, settings)
    assert (
        editorial_fingerprint({**article, "content": "changed"}, settings) != original
    )
    assert (
        editorial_fingerprint(article, {"prompts": {"editor": "changed"}}) != original
    )
    assert editorial_fingerprint({**article, "image_url": "new"}, settings) == original


def test_generated_pr_is_draft_and_requests_review_of_exact_artifact():
    git = MagicMock()
    git.create_pull_request.return_value = "https://github.com/org/repo/pull/1"
    writer = PROrchestrator(
        git, MagicMock(), {"target_repo_url": "https://github.com/org/repo"}
    )
    writer.create_pr(
        article_id="1",
        article={"source_name": "NASA", "source_url": "https://science.nasa.gov/"},
        branch_name="article",
        output_filename="article.md",
        content_sha256="a" * 64,
        review_notes="Actual evidence and unresolved uncertainty",
    )
    request = git.create_pull_request.call_args.kwargs
    assert request["draft"] is True
    assert "a" * 64 in request["body"]
    assert "Final human editorial review — PENDING" in request["body"]
    assert "Actual evidence and unresolved uncertainty" in request["body"]
    assert "origin=unknown" in request["body"]
    assert "this checklist does not enforce or attest a review" in request["body"]


def test_source_backed_replay_detects_exact_negative_controls(tmp_path):
    from pathlib import Path

    from tools.editorial_eval.assertions import get_assert
    from tools.editorial_eval.prepare import prepare_replay

    corpus = Path(__file__).resolve().parents[2] / "data/editorial_eval/evidence"
    cases = [
        json.loads(line) for line in (corpus / "cases.jsonl").read_text().splitlines()
    ]
    assert len(cases) == 11
    assert all(case["source_url"].startswith("https://") for case in cases)
    assert all(case["review_evidence"] is None for case in cases)
    failures = []
    for label in ("baseline", "candidate"):
        outputs = {
            row["case_id"]: row
            for row in (
                json.loads(line)
                for line in (corpus / f"{label}.jsonl").read_text().splitlines()
            )
        }
        for case in cases:
            result = get_assert(
                outputs[case["case_id"]]["output"],
                {"vars": {**case, "stored_error": None}},
            )
            if not result["pass"]:
                failures.append((label, case["case_id"]))
    assert set(failures) == {
        ("candidate", case["case_id"])
        for case in cases
        if case["case_id"] != "faithful_limit"
    }
    review = json.loads((corpus / "review.json").read_text())
    assert review["human_review"]["status"] == "pending"
    summary = prepare_replay(
        cases_path=corpus / "cases.jsonl",
        baseline_path=corpus / "baseline.jsonl",
        candidate_path=corpus / "candidate.jsonl",
        output_dir=tmp_path / "replay",
    )
    assert summary.case_count == 11


def test_enrichment_and_source_review_preserve_negation_and_expose_transport_failure():
    agent = object.__new__(EditorAgent)
    agent.prompts = {"fact_check_verification": {"system": "Check supplied source"}}
    label = "Estar en la zona habitable no garantiza que un planeta esté habitado."
    source = "Detection of a single biosignature by any means does not constitute discovery of life."
    calls = []

    def unavailable(prompt, system):
        calls.append(prompt)
        raise TimeoutError("bounded provider timeout")

    agent._send_fact_check_prompt = unavailable
    claims = agent._verify_fact_check_claims(
        [{"label": label, "status": "confirmed"}], source, "Life", "summary_only"
    )
    assert claims == [{"label": label, "status": "uncertain"}]
    assert label in calls[0]
    assert agent.last_source_support_verdict == {
        "verification_status": "unverified",
        "claims_checked": 0,
        "issues": ["TimeoutError"],
    }


def _pipeline_with_provider_responses(
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
    body = (
        "El estudio describe una observación limitada y no demuestra causalidad. "
        "La fuente explica el método y sus límites; faltan estudios posteriores. "
    ) * 12
    responses = iter(reviews)
    scores = iter(technical_scores) if technical_scores is not None else None
    headline_responses = (
        iter(headline_reviews) if headline_reviews is not None else None
    )
    headline_rejected = False
    agent.recorded_repair_prompts = []
    suffixes = iter(repair_suffix) if isinstance(repair_suffix, list) else None

    def send(prompt, system="", **kwargs):
        nonlocal headline_rejected
        if system.startswith(agent.prompts["editor_critic"]["system"]):
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response if isinstance(response, str) else json.dumps(response)
        if system.startswith(agent.prompts["headline_critic"]["system"]):
            if headline_responses is not None:
                response = next(headline_responses)
                if isinstance(response, Exception):
                    raise response
                if isinstance(response, dict) and response.get("approved") is False:
                    headline_rejected = True
                return response if isinstance(response, str) else json.dumps(response)
            return json.dumps(
                {"approved": True, "fidelity_pass": True, "sensationalism_pass": True}
            )
        if system.startswith(agent.prompts["headline"]["system"]):
            if empty_after_rejection and headline_rejected:
                return "{}"
            return json.dumps(
                {
                    "direct": "Una observación que requiere nuevos estudios",
                    "question": "¿Qué limita la observación?",
                    "benefit": "Los límites de este estudio",
                    "excerpt": "La observación descrita tiene límites y requiere estudios posteriores.",
                    "tags": ["observacion"],
                }
            )
        if system.startswith(agent.prompts["enrichment"]["system"]):
            return json.dumps(
                {
                    "summary_points": ["Observación limitada", "No prueba causalidad"],
                    "glossary": [{"term": "Observación", "definition": "Un registro"}],
                    "fact_check": [
                        {"label": "No prueba causalidad", "status": "uncertain"}
                    ],
                    "why_it_matters": [],
                    "confidence": "Limitada",
                    "sources": [
                        {"title": "Fuente", "url": "https://example.org/source"}
                    ],
                }
            )
        if prompt.startswith("Analyze the following text across four criteria"):
            return json.dumps(
                {"score": 95, "reason": "Spanish complete article", "recoverable": True}
            )
        if prompt.startswith("La versión anterior fue rechazada"):
            agent.recorded_repair_prompts.append(prompt)
            return body + (next(suffixes) if suffixes is not None else repair_suffix)
        return body

    agent._send_prompt = send
    agent._send_fact_check_prompt = lambda *args, **kwargs: {"status": "uncertain"}
    article = {
        "id": "hold-one",
        "title": "Una observación limitada",
        "content": body,
        "url": "https://example.org/source",
        "source_name": "Fuente",
        "category": "espacio",
    }
    return agent, article, body


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("provider unavailable"),
        "malformed verdict",
        _verdict(material_claims_supported=True, value_add_assessment=None),
    ],
)
@pytest.mark.parametrize("changed_repair", [False, True])
@pytest.mark.parametrize("finding", ["unsupported", "close_paraphrase"])
def test_known_material_hold_survives_unverified_rereview_and_resume(
    tmp_path, monkeypatch, failure, changed_repair, finding
):
    from news_collector.components.editorial.editorial_publication_artifact import (
        GeneratedArticleValidationError,
    )
    from news_collector.components.editorial.editorial_stages import EditorialStage

    issue = "Concrete unsupported claim remains in the draft"
    rejected = _verdict(
        material_claims_supported=finding != "unsupported",
        value_add_assessment=(
            "close_paraphrase" if finding == "close_paraphrase" else "substantive"
        ),
        support_issues=[issue],
    )
    suffix = "\n\nUna reparación requiere nueva revisión." if changed_repair else ""
    agent, article, body = _pipeline_with_provider_responses(
        tmp_path, monkeypatch, [rejected, failure, failure], suffix
    )
    for _ in range(2):
        with pytest.raises(GeneratedArticleValidationError) as exc:
            agent.prepare_article(article, override_date="2024-06-05")
        assert exc.value.error_code == "E_EDITORIAL_EVIDENCE"
        assert agent.last_critic_verdict["approved"] is False
        assert issue in agent.last_critic_verdict["support_issues"]
    artifact = json.loads(
        agent._get_cache_path(
            "hold-one", EditorialStage.EDITORIAL_CRITIC_OK
        ).read_text()
    )
    candidate = agent._get_cache_path("hold-one", EditorialStage.EDITORIAL).read_text()
    assert artifact["content_sha256"] == hashlib.sha256(candidate.encode()).hexdigest()
    assert (
        artifact["verdict"]["reviewed_content_sha256"]
        == hashlib.sha256(body.encode()).hexdigest()
    )
    assert artifact["verdict"]["verification_status"] == "unverified"
    assert suffix in candidate
    assert issue in agent.recorded_repair_prompts[0]


def test_verified_repair_clears_hold_and_only_that_candidate_gets_checkpoint(
    tmp_path, monkeypatch
):
    from news_collector.components.editorial.editorial_stages import EditorialStage

    agent, article, _ = _pipeline_with_provider_responses(
        tmp_path,
        monkeypatch,
        [_verdict(material_claims_supported=False), _verdict()],
        "\n\nEl texto corregido conserva la incertidumbre.",
    )
    draft = agent.prepare_article(article, override_date="2024-06-05")
    assert "El texto corregido conserva la incertidumbre." in draft.preview_markdown
    assert agent.last_critic_verdict["approved"] is True
    artifact = json.loads(
        agent._get_cache_path(
            "hold-one", EditorialStage.EDITORIAL_CRITIC_OK
        ).read_text()
    )
    candidate = agent._get_cache_path("hold-one", EditorialStage.EDITORIAL).read_text()
    assert (
        artifact["verdict"]["reviewed_content_sha256"]
        == artifact["content_sha256"]
        == hashlib.sha256(candidate.encode()).hexdigest()
    )


@pytest.mark.parametrize("changed", ["article", "source", "prompt"])
def test_material_hold_does_not_leak_to_another_article_or_revision(
    tmp_path, monkeypatch, changed
):
    from news_collector.components.editorial.editorial_publication_artifact import (
        GeneratedArticleValidationError,
    )

    agent, article, _ = _pipeline_with_provider_responses(
        tmp_path,
        monkeypatch,
        [
            _verdict(material_claims_supported=False),
            TimeoutError("down"),
            TimeoutError("still down"),
        ],
    )
    with pytest.raises(GeneratedArticleValidationError):
        agent.prepare_article(article, override_date="2024-06-05")
    if changed == "article":
        article["id"] = "hold-two"
    elif changed == "source":
        article["content"] += " La fuente ahora contiene un dato adicional."
    else:
        agent.prompts["editor"]["system"] += " Preserve limitations."
    draft = agent.prepare_article(article, override_date="2024-06-05")
    assert draft.preview_markdown
    assert agent.last_critic_verdict["verification_status"] == "unverified"
    assert "material_claims_supported" not in agent.last_critic_verdict


def test_known_material_hold_survives_technical_repair_on_resume(tmp_path, monkeypatch):
    from news_collector.components.editorial.editorial_publication_artifact import (
        GeneratedArticleValidationError,
    )

    issue = "The unsupported material claim still needs explicit revalidation"
    agent, article, _ = _pipeline_with_provider_responses(
        tmp_path,
        monkeypatch,
        [
            _verdict(material_claims_supported=False, support_issues=[issue]),
            TimeoutError("first review unavailable"),
            TimeoutError("resume review unavailable"),
        ],
        repair_suffix=[
            "",
            "\n\nReparación técnica: texto cambiado sin revisión material.",
        ],
        technical_scores=[95, 95, 0, 95],
    )
    for _ in range(2):
        with pytest.raises(GeneratedArticleValidationError) as exc:
            agent.prepare_article(article, override_date="2024-06-05")
        assert exc.value.error_code == "E_EDITORIAL_EVIDENCE"
    assert issue in agent.last_critic_verdict["support_issues"]
    assert agent.last_critic_verdict["material_claims_supported"] is False


@pytest.mark.parametrize(
    "failure", [TimeoutError("headline provider unavailable"), "malformed verdict"]
)
def test_known_headline_rejection_survives_unverified_rereview_and_resume(
    tmp_path, monkeypatch, failure
):
    from news_collector.components.editorial.editorial_publication_artifact import (
        GeneratedArticleValidationError,
    )
    from news_collector.components.editorial.editorial_stages import EditorialStage

    instruction = "Remove fabricated inhabited-Mars promise unsupported by the body"
    rejected = {
        "approved": False,
        "fidelity_pass": False,
        "sensationalism_pass": True,
        "regenerate_instruction": instruction,
    }
    agent, article, _ = _pipeline_with_provider_responses(
        tmp_path,
        monkeypatch,
        [_verdict()],
        headline_reviews=[rejected] + [failure] * 5,
    )
    for _ in range(2):
        with pytest.raises(GeneratedArticleValidationError) as exc:
            agent.prepare_article(article, override_date="2024-06-05")
        assert exc.value.error_code == "E_HEADLINE_EVIDENCE"
        assert agent.last_headline_verdict["fidelity_pass"] is False
        assert agent.last_headline_verdict["regenerate_instruction"] == instruction
    artifact = json.loads(
        agent._get_cache_path(
            "hold-one", EditorialStage.HEADLINE_CRITIC_REVIEW
        ).read_text()
    )
    assert artifact["verdict"]["regenerate_instruction"] == instruction
    assert artifact["headlines_sha256"]
    assert artifact["body_sha256"]


def test_known_headline_rejection_survives_empty_regeneration(tmp_path, monkeypatch):
    from news_collector.components.editorial.editorial_publication_artifact import (
        GeneratedArticleValidationError,
    )

    agent, article, _ = _pipeline_with_provider_responses(
        tmp_path,
        monkeypatch,
        [_verdict()],
        empty_after_rejection=True,
        headline_reviews=[
            {
                "approved": False,
                "fidelity_pass": False,
                "sensationalism_pass": True,
                "regenerate_instruction": "Remove invented headline claim",
            }
        ],
    )
    with pytest.raises(GeneratedArticleValidationError) as exc:
        agent.prepare_article(article, override_date="2024-06-05")
    assert exc.value.error_code == "E_HEADLINE_EVIDENCE"
    assert (
        agent.last_headline_verdict["regenerate_instruction"]
        == "Remove invented headline claim"
    )


def test_successful_headline_revalidation_clears_known_rejection(tmp_path, monkeypatch):
    agent, article, _ = _pipeline_with_provider_responses(
        tmp_path,
        monkeypatch,
        [_verdict()],
        headline_reviews=[
            {
                "approved": False,
                "fidelity_pass": False,
                "sensationalism_pass": True,
                "regenerate_instruction": "Remove invented headline claim",
            },
            {"approved": True, "fidelity_pass": True, "sensationalism_pass": True},
        ],
    )
    draft = agent.prepare_article(article, override_date="2024-06-05")
    assert draft.preview_markdown
    assert agent.last_headline_verdict["approved"] is True
    assert agent.last_headline_verdict["verification_status"] == "reviewed"


@pytest.mark.parametrize("changed", ["article", "source", "prompt"])
def test_headline_hold_does_not_leak_to_another_article_or_revision(
    tmp_path, monkeypatch, changed
):
    from news_collector.components.editorial.editorial_publication_artifact import (
        GeneratedArticleValidationError,
    )

    failed_review = TimeoutError("headline provider unavailable")
    agent, article, _ = _pipeline_with_provider_responses(
        tmp_path,
        monkeypatch,
        [_verdict(), _verdict()],
        headline_reviews=[
            {
                "approved": False,
                "fidelity_pass": False,
                "sensationalism_pass": True,
                "regenerate_instruction": "Known unsupported headline",
            },
            failed_review,
            failed_review,
            failed_review,
        ],
    )
    with pytest.raises(GeneratedArticleValidationError):
        agent.prepare_article(article, override_date="2024-06-05")
    if changed == "article":
        article["id"] = "hold-two"
    elif changed == "source":
        article["content"] += " La fuente incluye una precisión nueva."
    else:
        agent.prompts["headline"]["system"] += " Preserve uncertainty."
    draft = agent.prepare_article(article, override_date="2024-06-05")
    assert draft.preview_markdown
    assert agent.last_headline_verdict["verification_status"] == "unverified"
    assert "fidelity_pass" not in agent.last_headline_verdict
