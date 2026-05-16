import re

import pytest
from news_collector.components.editorial.ai_editor import EditorAgent
from news_collector.infrastructure.llm.model_registry import InvalidModelIdError
from noticiencias.config_schema import OllamaConfig
from pydantic import ValidationError


class MockProvider:
    def __init__(self, api_url, model, timeout):
        self.api_url = api_url
        self.model = model
        self.timeout = timeout


def _mock_min_length_config():
    return type(
        "C", (), {"text_processing": type("TP", (), {"min_content_length": 100})}
    )()


def test_config_validation():
    # Valid names
    OllamaConfig(model="llama3.2")
    OllamaConfig(model="llama3.2:latest")
    OllamaConfig(model="my-custom-model.123")

    # Invalid names
    with pytest.raises(ValidationError):
        OllamaConfig(model="Invalid Space")
    with pytest.raises(ValidationError):
        OllamaConfig(model="<script>")
    with pytest.raises(ValidationError):
        OllamaConfig(model="")


def test_model_resolution_without_network(monkeypatch):
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.get_provider",
        lambda api_url=None, model=None, timeout=300, **kw: MockProvider(
            api_url, model, timeout
        ),
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.load_config",
        _mock_min_length_config,
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.EditorAgent._load_prompts",
        lambda self: {},
    )

    agent = EditorAgent(
        api_url="http://mock",
        model="llama3.3",  # canonicalized to :latest
        translator_model="mistral:7b",
        editor_model="qwen2.5:14b",
        headlines_model=None,  # uses base model
    )

    assert agent.model == "llama3.3:latest"
    assert agent.translator_model == "mistral:7b"
    assert agent.editor_model == "qwen2.5:14b"
    assert agent.headlines_model == "llama3.3:latest"


def test_invalid_stage_override_fails_fast(monkeypatch):
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.get_provider",
        lambda api_url=None, model=None, timeout=300, **kw: MockProvider(
            api_url, model, timeout
        ),
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.load_config",
        _mock_min_length_config,
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.EditorAgent._load_prompts",
        lambda self: {},
    )

    with pytest.raises(InvalidModelIdError) as excinfo:
        EditorAgent(
            api_url="http://mock",
            model="llama3.3:latest",
            translator_model="bad model",
        )
    message = str(excinfo.value)
    assert "translator" in message
    assert "bad model" in message
    assert "Use '<model>:<tag>'" in message


def test_translation_pipeline_preserves_payload_shape_and_provenance(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.get_provider",
        lambda api_url=None, model=None, timeout=300, **kw: MockProvider(
            api_url, model, timeout
        ),
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.load_config",
        _mock_min_length_config,
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.EditorAgent._load_prompts",
        lambda self: {},
    )

    agent = EditorAgent(
        api_url="http://mock",
        model="llama3.3:latest",
        translator_model="mistral:7b",
        editor_model="qwen2.5:14b",
        headlines_model="llama3.2:latest",
    )
    agent.cache_dir = tmp_path / "cache"
    agent.cache_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(agent, "_translate_scientific", lambda _: "Texto traducido")
    monkeypatch.setattr(
        agent,
        "_adapt_editorial",
        lambda *args, **kwargs: (
            "## Apertura\n"
            "Este análisis examina los avances recientes en el campo científico y tecnológico. "
            "Los investigadores han identificado nuevos patrones que permiten comprender mejor los "
            "fenómenos estudiados en este dominio. El trabajo demuestra resultados significativos "
            "para la comunidad científica internacional. Las implicaciones de estos hallazgos se "
            "extienden a múltiples disciplinas y abren nuevas líneas de investigación prometedoras. "
            "La metodología empleada resulta reproducible y transparente, lo que fortalece la "
            "credibilidad del estudio. En conclusión, estos resultados contribuyen al avance del "
            "conocimiento en el área y representan un paso importante para futuras investigaciones."
        ),
    )
    monkeypatch.setattr(agent, "_critic_pass", lambda _: (True, None))
    monkeypatch.setattr(
        agent,
        "_critic_editorial_pass",
        lambda *args, **kwargs: (True, None, True),
    )
    monkeypatch.setattr(
        agent,
        "_generate_headlines",
        lambda _: {
            "direct": "Título auditado",
            "question": "¿Por qué importa?",
            "benefit": "Contexto para tomar decisiones informadas.",
            "excerpt": "Resumen auditado suficientemente largo para metadatos.",
            "tags": ["inteligencia_artificial"],
        },
    )
    monkeypatch.setattr(agent, "_repair_output", lambda c, h, _i: (c, h))

    article = {
        "id": "160",
        "title": "Legacy payload identity check title",
        "summary": "Resumen inicial",
        "content": "Contenido base " * 30,
        "url": "https://example.com/article-160",
        "source_id": "lilian_weng",
        "source_name": "Lil'Log",
        "metadata": {"category": "technology"},
    }
    before_keys = sorted(article.keys())

    output = agent.process_article(article, override_date="2024-07-07")
    after_keys = sorted(article.keys())

    assert before_keys == after_keys
    assert "source_identity: source_id=lilian_weng; source_name=Lil'Log" in output


def test_provenance_comment_is_single_and_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.get_provider",
        lambda api_url=None, model=None, timeout=300, **kw: MockProvider(
            api_url, model, timeout
        ),
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.load_config",
        _mock_min_length_config,
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.ai_editor.EditorAgent._load_prompts",
        lambda self: {},
    )

    agent = EditorAgent(
        api_url="http://mock",
        model="llama3.3:latest",
        translator_model="mistral:7b",
        editor_model="qwen2.5:14b",
        headlines_model="llama3.2:latest",
    )
    agent.cache_dir = tmp_path / "cache"
    agent.cache_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(agent, "_translate_scientific", lambda _: "Texto traducido")
    monkeypatch.setattr(
        agent,
        "_adapt_editorial",
        lambda *args, **kwargs: (
            "## Apertura\n"
            "Este análisis examina los avances recientes en el campo científico y tecnológico. "
            "Los investigadores han identificado nuevos patrones que permiten comprender mejor los "
            "fenómenos estudiados en este dominio. El trabajo demuestra resultados significativos "
            "para la comunidad científica internacional. Las implicaciones de estos hallazgos se "
            "extienden a múltiples disciplinas y abren nuevas líneas de investigación prometedoras. "
            "La metodología empleada resulta reproducible y transparente, lo que fortalece la "
            "credibilidad del estudio. En conclusión, estos resultados contribuyen al avance del "
            "conocimiento en el área y representan un paso importante para futuras investigaciones.\n\n"
            "<!-- source_identity: source_id=legacy_source; source_name=Legacy Name -->"
        ),
    )
    monkeypatch.setattr(agent, "_critic_pass", lambda _: (True, None))
    monkeypatch.setattr(
        agent,
        "_critic_editorial_pass",
        lambda *args, **kwargs: (True, None, True),
    )
    monkeypatch.setattr(
        agent,
        "_generate_headlines",
        lambda _: {
            "direct": "Título auditado",
            "question": "¿Por qué importa?",
            "benefit": "Contexto para tomar decisiones informadas.",
            "excerpt": "Resumen auditado suficientemente largo para metadatos.",
            "tags": ["inteligencia_artificial"],
        },
    )
    monkeypatch.setattr(agent, "_repair_output", lambda c, h, _i: (c, h))

    article = {
        "id": "160",
        "title": "Legacy payload identity check title",
        "summary": "Resumen inicial",
        "content": "Contenido base " * 30,
        "url": "https://example.com/article-160",
        "source_id": "lilian_weng",
        "source_name": "Lil'Log",
        "metadata": {"category": "technology"},
    }

    output_first = agent.process_article(article, override_date="2024-07-07")
    output_second = agent.process_article(article, override_date="2024-07-07")

    canonical_comment = (
        "<!-- source_identity: source_id=lilian_weng; source_name=Lil'Log -->"
    )
    canonical_pattern = re.compile(
        r"<!-- source_identity: source_id=[^;]+; source_name=[^\n>]+ -->"
    )

    assert output_first == output_second
    assert output_second.count("<!-- source_identity:") == 1
    assert canonical_comment in output_second
    assert canonical_pattern.search(output_second)
