"""Regression tests for the GUI configuration helpers."""
from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest

from noticiencias.config_schema import DEFAULT_CONFIG
from noticiencias.gui_config import ConfigEditor


class _TkVariableStub:
    """Minimal stand-in for tkinter variable classes."""

    def __init__(self, value: str | None = None) -> None:
        self._value = value

    def get(self) -> str | None:
        return self._value

    def set(self, value: str | None) -> None:
        self._value = value


@pytest.fixture(name="tk_runtime_shim")
def _tk_runtime_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide lightweight tkinter shims to avoid GUI dependencies."""

    root_surrogate = SimpleNamespace(
        title=lambda *_args, **_kwargs: None,
        rowconfigure=lambda *_args, **_kwargs: None,
        columnconfigure=lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(tk, "Tk", lambda: root_surrogate)
    monkeypatch.setattr(tk, "StringVar", _TkVariableStub)
    monkeypatch.setattr(tk, "BooleanVar", _TkVariableStub)
    monkeypatch.setattr(ConfigEditor, "_build_ui", lambda self: None)
    monkeypatch.setattr(ConfigEditor, "_apply_filter", lambda self: None)


def test_format_display_handles_model_config(tk_runtime_shim: None) -> None:
    """Ensure model-backed defaults are rendered without serialization errors."""

    editor = ConfigEditor(DEFAULT_CONFIG)
    field_doc = editor._field_docs["enrichment.models"]

    rendered = editor._format_display(field_doc.default)

    assert isinstance(rendered, str)
    assert "pattern_v1" in rendered
