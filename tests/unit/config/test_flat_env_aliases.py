"""Flat .env aliases map to nested config keys (GEMINI_API_KEY -> gemini.api_key)."""

from __future__ import annotations

from pathlib import Path

from noticiencias.config_manager import load_config


def _config(tmp_path: Path, env_text: str) -> Path:
    (tmp_path / ".env").write_text(env_text, encoding="utf-8")
    cfg = tmp_path / "config.toml"
    cfg.write_text("[app]\nenvironment = 'development'\n", encoding="utf-8")
    return cfg


def test_flat_gemini_key_alias_is_loaded_from_dotenv(tmp_path):
    cfg = load_config(_config(tmp_path, "GEMINI_API_KEY=flat-key\n"), environ={})
    assert cfg.gemini.api_key == "flat-key"


def test_prefixed_gemini_key_wins_over_flat_alias(tmp_path):
    env = "GEMINI_API_KEY=flat-key\nNOTICIENCIAS__GEMINI__API_KEY=prefixed-key\n"
    cfg = load_config(_config(tmp_path, env), environ={})
    assert cfg.gemini.api_key == "prefixed-key"


def test_missing_gemini_key_stays_unset(tmp_path):
    cfg = load_config(_config(tmp_path, "GITHUB_TOKEN=x\n"), environ={})
    assert cfg.gemini.api_key is None
