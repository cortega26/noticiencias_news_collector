"""Utility helpers for retrieving runtime secrets from environment or vault files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class SecretLoader:
    """Lightweight helper to centralize secret retrieval.

    The loader reads secrets from (in order):
    1. Environment variables.
    2. A JSON file pointed by ``SECRET_MANAGER_FILE`` or ``VAULT_SECRETS_PATH``.

    This keeps credentials out of the repository while allowing local development
    without a full vault deployment. Production setups can symlink the JSON loader
    to a process that keeps values in sync with HashiCorp Vault, AWS Secrets Manager,
    GCP Secret Manager, etc.
    """

    def __init__(self) -> None:
        self._cache: Optional[Dict[str, str]] = None

    def _load_secret_file(self) -> Dict[str, str]:
        if self._cache is not None:
            return self._cache

        path_value = os.getenv("SECRET_MANAGER_FILE") or os.getenv("VAULT_SECRETS_PATH")
        if not path_value:
            self._cache = {}
            return self._cache

        candidate = Path(path_value).expanduser()
        if not candidate.exists():
            self._cache = {}
            return self._cache

        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                normalized = {str(k).upper(): str(v) for k, v in data.items()}
            else:
                normalized = {}
        except Exception:
            normalized = {}

        self._cache = normalized
        return self._cache

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        env_key = key.upper()
        if env_key in os.environ:
            return os.environ[env_key]

        store = self._load_secret_file()
        return store.get(env_key, default)

    def database_config(self, sqlite_path: Path) -> Dict[str, Any]:
        """Return the database configuration, preferring DATABASE_URL secrets."""

        database_url = self.get("DATABASE_URL")
        if not database_url:
            return {"type": "sqlite", "path": sqlite_path}

        try:
            from sqlalchemy.engine import make_url

            url = make_url(database_url)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise ValueError(f"DATABASE_URL inválida: {exc}") from exc

        backend = url.get_backend_name()
        config: Dict[str, Any] = {
            "type": backend,
            "url": database_url,
            "options": {},
        }

        if backend == "sqlite":
            # sqlite:///relative/path.db -> url.database is already a string path
            db_path = Path(url.database) if url.database else sqlite_path
            config["path"] = db_path
        else:
            # For server databases the SQLAlchemy engine can consume the URL directly.
            config["host"] = url.host
            config["port"] = url.port
            config["database"] = url.database
            config["username"] = url.username
            config["password_env_var"] = "DATABASE_URL"

        return config


secret_loader = SecretLoader()

__all__ = ["SecretLoader", "secret_loader"]
