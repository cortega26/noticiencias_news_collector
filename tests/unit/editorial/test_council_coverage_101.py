"""Plan 101 coverage backfill: EditorialCouncil.evaluate_article branches.

Covers the content-truncation path, error/str/non-dict responses and the
outer exception guard with a fake LLM client (no ambient config needed).
"""

from __future__ import annotations

from news_collector.editorial.council import EditorialCouncil


class FakeLLM:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.seen_prompts = []

    def generate_sync(self, **kwargs):
        self.seen_prompts.append(kwargs.get("prompt", ""))
        if self.exc is not None:
            raise self.exc
        return self.response


def _approved_payload():
    return {
        "council_assessments": [
            {"role": "Científico", "score": 4, "observation": "Good"},
            {"role": "Escéptico", "score": 4, "observation": "Good"},
            {"role": "Curioso", "score": 5, "observation": "Great"},
            {"role": "Editor", "score": 5, "observation": "perfect"},
        ],
        "editorial_synthesis": {},
        "editor_approval": "Sí, es Noticiencias",
    }


def test_content_is_truncated_into_prompt():
    council = EditorialCouncil(llm_client=FakeLLM(response=_approved_payload()))
    result = council.evaluate_article("Title", "Summary", content="x" * 5000)
    assert result is not None and result.is_approved
    prompt = council.llm.seen_prompts[0]
    assert "FRAGMENTO CONTENIDO" in prompt
    assert len(prompt) < 5000 + 500  # content truncated to 1500 chars


def test_error_response_declines():
    council = EditorialCouncil(llm_client=FakeLLM(response={"error": "boom"}))
    assert council.evaluate_article("Title", "Summary") is None


def test_string_json_response_is_parsed():
    import json

    council = EditorialCouncil(
        llm_client=FakeLLM(response=json.dumps(_approved_payload()))
    )
    result = council.evaluate_article("Title", "Summary")
    assert result is not None and result.is_approved


def test_unparseable_string_response_declines():
    council = EditorialCouncil(llm_client=FakeLLM(response="{not json"))
    assert council.evaluate_article("Title", "Summary") is None


def test_non_dict_response_declines():
    council = EditorialCouncil(llm_client=FakeLLM(response=["unexpected"]))
    assert council.evaluate_article("Title", "Summary") is None


def test_provider_exception_declines():
    council = EditorialCouncil(llm_client=FakeLLM(exc=RuntimeError("provider down")))
    assert council.evaluate_article("Title", "Summary") is None
