"""Tests for scripts/validate_export.py empty-export handling.

An empty export must FAIL validation by default (it is a CI gate), and only
pass when --allow-empty is explicitly set.
"""

from __future__ import annotations

import json

from scripts.validate_export import validate_export


def _write_empty_export(tmp_path):
    path = tmp_path / "export.json"
    path.write_text(json.dumps({"schema_version": 1, "articles": []}), encoding="utf-8")
    return path


def test_empty_export_fails_by_default(tmp_path):
    path = _write_empty_export(tmp_path)
    assert validate_export(path) is False


def test_empty_export_passes_with_allow_empty(tmp_path):
    path = _write_empty_export(tmp_path)
    assert validate_export(path, allow_empty=True) is True


def test_valid_non_empty_export_passes(tmp_path):
    path = tmp_path / "export.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "articles": [
                    {
                        "title": "Titulo",
                        "url": "https://example.com/a",
                        "source_id": "src",
                        "published_date": "2026-06-13T00:00:00+00:00",
                        "summary": "Resumen.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert validate_export(path) is True
