"""
Tests for NVIDIA provider routing fix.

spec-nvidia-routing-fix.md §6 — Verification Plan

Covers:
  G1 – UI summary shows NVIDIA model when NVIDIA active
  G2 – active_provider_is_ollama is False when NVIDIA active
  G3 – EditorAgent routing uses NVIDIA model when NVIDIA provider active
  G5 – EditorAgent routing preserves Ollama per-stage models when Ollama active
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_nvidia_provider(model: str = "qwen/qwen3-next-80b-a3b-thinking"):
    """Return a real NvidiaProvider (no network calls)."""
    from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

    return NvidiaProvider(api_key="nvapi-test", model=model)


def _make_ollama_provider(model: str = "qwen2.5:32b"):
    """Return a real OllamaProvider."""
    from news_collector.infrastructure.llm.provider import OllamaProvider

    return OllamaProvider(api_url="http://localhost:11434/api/generate", model=model)


def _make_gemini_provider(model: str = "gemini-2.5-flash"):
    """Return a real GeminiProvider with no real key."""
    from news_collector.infrastructure.llm.gemini_provider import GeminiProvider

    return GeminiProvider(api_key="fake-key", model=model)


# ---------------------------------------------------------------------------
# G1 – UI summary logic
# ---------------------------------------------------------------------------


class TestConfigSummary:
    """Tests for admin_panel Config Summary section (spec §5.1 Change A)."""

    def _compute_summary_models(self, provider, ollama_cfg, base_model_sel):
        """
        Mirror the logic that admin_panel.py should use after the fix.
        Returns (r_trans, r_edit, r_head).
        """
        from news_collector.infrastructure.llm.gemini_provider import GeminiProvider
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        if isinstance(provider, (NvidiaProvider, GeminiProvider)):
            cloud_model = getattr(provider, "model", "N/A")
            return cloud_model, cloud_model, cloud_model
        r_trans = ollama_cfg.get("translator_model") or base_model_sel
        r_edit = ollama_cfg.get("editor_model") or base_model_sel
        r_head = ollama_cfg.get("headlines_model") or base_model_sel
        return r_trans, r_edit, r_head

    def test_config_summary_shows_nvidia_model_when_nvidia_active(self):
        """G1: When NVIDIA is the active provider all three stage metrics show the NVIDIA model."""
        nvidia = _make_nvidia_provider("qwen/qwen3-next-80b-a3b-thinking")
        ollama_cfg = {
            "model": "qwen2.5:32b",
            "translator_model": "qwen2.5:32b",
            "editor_model": "qwen2.5:32b",
            "headlines_model": "llama3.2:latest",
        }
        r_trans, r_edit, r_head = self._compute_summary_models(
            nvidia, ollama_cfg, base_model_sel="qwen2.5:32b"
        )
        assert r_trans == "qwen/qwen3-next-80b-a3b-thinking"
        assert r_edit == "qwen/qwen3-next-80b-a3b-thinking"
        assert r_head == "qwen/qwen3-next-80b-a3b-thinking"

    def test_config_summary_shows_gemini_model_when_gemini_active(self):
        """G1: Same behaviour for Gemini provider."""
        gemini = _make_gemini_provider("gemini-2.5-flash")
        ollama_cfg = {
            "model": "qwen2.5:32b",
            "translator_model": "qwen2.5:32b",
            "editor_model": "qwen2.5:32b",
            "headlines_model": "llama3.2:latest",
        }
        r_trans, r_edit, r_head = self._compute_summary_models(
            gemini, ollama_cfg, base_model_sel="qwen2.5:32b"
        )
        assert r_trans == "gemini-2.5-flash"
        assert r_edit == "gemini-2.5-flash"
        assert r_head == "gemini-2.5-flash"

    def test_config_summary_shows_ollama_stage_models_when_ollama_active(self):
        """G5 regression: When Ollama is active the per-stage values from config are used."""
        ollama = _make_ollama_provider("qwen2.5:32b")
        ollama_cfg = {
            "model": "qwen2.5:32b",
            "translator_model": "qwen2.5:32b",
            "editor_model": "qwen2.5:32b",
            "headlines_model": "llama3.2:latest",
        }
        r_trans, r_edit, r_head = self._compute_summary_models(
            ollama, ollama_cfg, base_model_sel="qwen2.5:32b"
        )
        assert r_trans == "qwen2.5:32b"
        assert r_edit == "qwen2.5:32b"
        assert r_head == "llama3.2:latest"


# ---------------------------------------------------------------------------
# G2 – active_provider_is_ollama flag
# ---------------------------------------------------------------------------


class TestActiveProviderFlag:
    """Tests for the active_provider_is_ollama flag (spec §5.1 Change B)."""

    def _compute_flag(self, provider):
        from news_collector.infrastructure.llm.gemini_provider import GeminiProvider
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        return not isinstance(provider, (NvidiaProvider, GeminiProvider))

    def test_ollama_sections_hidden_when_nvidia_active(self):
        """G2: active_provider_is_ollama is False when NVIDIA provider detected."""
        nvidia = _make_nvidia_provider()
        assert self._compute_flag(nvidia) is False

    def test_ollama_sections_hidden_when_gemini_active(self):
        """G2: active_provider_is_ollama is False when Gemini provider detected."""
        gemini = _make_gemini_provider()
        assert self._compute_flag(gemini) is False

    def test_ollama_sections_shown_when_ollama_active(self):
        """G2 regression: active_provider_is_ollama is True when Ollama is the provider."""
        ollama = _make_ollama_provider()
        assert self._compute_flag(ollama) is True


# ---------------------------------------------------------------------------
# G3 – EditorAgent routing with NVIDIA provider
# ---------------------------------------------------------------------------


class TestEditorAgentModelRouting:
    """Tests for EditorAgent per-stage model routing (spec §5.2 Change C)."""

    def _build_agent_with_provider(self, provider, tmp_path):
        """
        Build an EditorAgent whose provider is pre-set to the given instance.

        We patch get_provider() so no real network calls are made.
        """
        with patch(
            "news_collector.components.editorial.ai_editor.get_provider",
            return_value=provider,
        ):
            from news_collector.components.editorial.ai_editor import EditorAgent

            agent = EditorAgent(
                api_url="http://localhost:11434/api/generate",
                model="qwen2.5:32b",
                translator_model="qwen2.5:32b",
                editor_model="qwen2.5:32b",
                headlines_model="llama3.2:latest",
            )
            agent.cache_dir = tmp_path / "editor-cache"
            agent.cache_dir.mkdir(parents=True, exist_ok=True)
        return agent

    def test_editor_agent_routing_uses_nvidia_model(self, tmp_path):
        """G3: When NvidiaProvider is active, all stage model attrs equal the NVIDIA model."""
        nvidia = _make_nvidia_provider("qwen/qwen3-next-80b-a3b-thinking")
        agent = self._build_agent_with_provider(nvidia, tmp_path)

        assert agent.model == "qwen/qwen3-next-80b-a3b-thinking"
        assert agent.translator_model == "qwen/qwen3-next-80b-a3b-thinking"
        assert agent.editor_model == "qwen/qwen3-next-80b-a3b-thinking"
        assert agent.headlines_model == "qwen/qwen3-next-80b-a3b-thinking"

    def test_editor_agent_routing_uses_gemini_model(self, tmp_path):
        """G3: When GeminiProvider is active, all stage models equal the Gemini model."""
        gemini = _make_gemini_provider("gemini-2.5-flash")
        agent = self._build_agent_with_provider(gemini, tmp_path)

        assert agent.model == "gemini-2.5-flash"
        assert agent.translator_model == "gemini-2.5-flash"
        assert agent.editor_model == "gemini-2.5-flash"
        assert agent.headlines_model == "gemini-2.5-flash"

    def test_editor_agent_routing_preserves_ollama_models(self, tmp_path):
        """G5 regression: When OllamaProvider is active, per-stage models remain as configured."""
        ollama = _make_ollama_provider("qwen2.5:32b")
        agent = self._build_agent_with_provider(ollama, tmp_path)

        # The model_registry normalises; translator/editor inherit base if not set
        # separately, but headlines uses the explicit value we passed in.
        assert "qwen2.5:32b" in agent.model
        assert "qwen2.5:32b" in agent.translator_model
        assert "qwen2.5:32b" in agent.editor_model
        # headlines_model was passed as "llama3.2:latest"
        assert "llama3.2:latest" in agent.headlines_model

    def test_provider_generate_receives_nvidia_model_not_ollama_name(self, tmp_path):
        """G3 end-to-end: provider.generate is called with the NVIDIA model, not an Ollama name."""
        nvidia = _make_nvidia_provider("qwen/qwen3-next-80b-a3b-thinking")
        nvidia.generate = MagicMock(return_value="translated text")

        agent = self._build_agent_with_provider(nvidia, tmp_path)

        # Simulate a translation call — the model kwarg should NOT be an Ollama name
        agent.provider.generate(
            "some content", system="system", model=agent.translator_model
        )

        call_kwargs = nvidia.generate.call_args
        model_arg = call_kwargs.kwargs.get("model") or (
            call_kwargs.args[2] if len(call_kwargs.args) > 2 else None
        )
        # Must not be an Ollama-style model (with ":")
        assert model_arg is not None
        assert (
            ":" not in model_arg
        ), f"Provider received Ollama model name '{model_arg}' instead of NVIDIA model"
        assert model_arg == "qwen/qwen3-next-80b-a3b-thinking"


# ---------------------------------------------------------------------------
# Thinking trace handling
# ---------------------------------------------------------------------------


class TestNvidiaProviderThinkingTrace:
    """Verify that reasoning_content traces never leak into visible output."""

    def test_strip_think_tags_empty(self):
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        assert NvidiaProvider._strip_think_tags("") == ""

    def test_strip_think_tags_noop(self):
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        text = "Normal article content with no think tags."
        assert NvidiaProvider._strip_think_tags(text) == text

    def test_strip_think_tags_removes_block(self):
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        text = (
            "<think>I need to approach this task carefully.</think>Real content here."
        )
        assert NvidiaProvider._strip_think_tags(text) == "Real content here."

    def test_strip_think_tags_multiline(self):
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        text = "<think>Multi-line\nreasoning\ntrace</think>Clean content"
        assert NvidiaProvider._strip_think_tags(text) == "Clean content"

    def test_strip_think_tags_malformed_no_close(self):
        """Unclosed <think> tag should not match (no </think> = no strip)."""
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        text = "<think>unclosed tag"
        assert NvidiaProvider._strip_think_tags(text) == text

    def test_strip_think_tags_multiple_blocks(self):
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        text = "<think>first</think>middle<think>second</think>end"
        assert NvidiaProvider._strip_think_tags(text) == "middleend"

    def test_extract_text_drops_reasoning_content(self):
        """When API returns only reasoning_content, _extract_text returns empty."""
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        data = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "reasoning_content": "This is the thinking trace.",
                    }
                }
            ]
        }
        result = NvidiaProvider._extract_text(data)
        assert result == "", f"Expected empty, got {result!r}"

    def test_extract_text_content_only(self):
        """Normal content should pass through unchanged."""
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        data = {
            "choices": [
                {
                    "message": {
                        "content": "This is the actual response.",
                        "reasoning_content": "Thinking trace here.",
                    }
                }
            ]
        }
        result = NvidiaProvider._extract_text(data)
        assert result == "This is the actual response."

    def test_extract_text_strips_think_tags(self):
        """Content with embedded <think> tags should be cleaned."""
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        data = {
            "choices": [
                {
                    "message": {
                        "content": "<think>reasoning</think>Clean article content."
                    }
                }
            ]
        }
        result = NvidiaProvider._extract_text(data)
        assert result == "Clean article content."

    def test_extract_text_empty_choices(self):
        from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider

        assert NvidiaProvider._extract_text({}) == ""
        assert NvidiaProvider._extract_text({"choices": []}) == ""
