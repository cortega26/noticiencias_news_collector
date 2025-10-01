"""Regression tests for the GUI configuration helpers."""
from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest

from noticiencias.config_schema import DEFAULT_CONFIG
from noticiencias.gui_config import ConfigEditor


class _DummyVar:
    """Minimal stand-in for tkinter variable classes."""

    def __init__(self, value: str | None = None) -> None:
        self._value = value

    def get(self) -> str | None:
        return self._value

    def set(self, value: str | None) -> None:
        self._value = value


@pytest.fixture(name="dummy_tk")
def _dummy_tk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide lightweight tkinter shims to avoid GUI dependencies."""

    dummy_root = SimpleNamespace(
        title=lambda *_args, **_kwargs: None,
        rowconfigure=lambda *_args, **_kwargs: None,
        columnconfigure=lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(tk, "Tk", lambda: dummy_root)
    monkeypatch.setattr(tk, "StringVar", _DummyVar)
    monkeypatch.setattr(tk, "BooleanVar", _DummyVar)
    monkeypatch.setattr(ConfigEditor, "_build_ui", lambda self: None)
    monkeypatch.setattr(ConfigEditor, "_apply_filter", lambda self: None)


def test_format_display_handles_model_config(dummy_tk: None) -> None:
    """Ensure model-backed defaults are rendered without serialization errors."""

    editor = ConfigEditor(DEFAULT_CONFIG)
    field_doc = editor._field_docs["enrichment.models"]

    rendered = editor._format_display(field_doc.default)

    assert isinstance(rendered, str)
    assert "pattern_v1" in rendered
