"""
Module role: Safe, serialized mutation of the source catalog
(`sources.yaml`) — Plan 060 / Phase 4b.

Owns:
- The single read-modify-validate-write-sync sequence every catalog
  mutation goes through, so atomicity, the advisory file lock and the
  DB-compensation logic exist exactly once.
- Request-scoped recovery: a DB-sync failure after the YAML write restores
  the prior catalog; if the restore itself fails, a durable
  `workflow_runs` row (`run_type='source_catalog_reconciliation'`) records
  the inconsistency instead of dropping it.
- The single-writer deployment assumption is documented in
  `docs/database_deployment.md`; the lock is advisory (`fcntl.flock`) and
  does not protect against a second concurrently-deployed instance.

Does NOT own:
- HTTP request parsing/response mapping (`serving/api.py` stays a thin
  wrapper) or the DB writes themselves (the caller passes `db_sync_fn`).
- Validation rules: reuses `validate_source_catalog()` from
  `news_collector.config.sources` (the same checker the pipeline's own
  startup validation uses).
- Crash-safe recovery between the YAML write and the DB sync: a process
  crash in that window leaves YAML/DB briefly divergent until the next
  successful mutation, which the phase spec judged acceptable (the atomic
  write already prevents a crash *during* the write from corrupting the
  live file).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import yaml

from news_collector.config.sources import (
    SOURCES_YAML_PATH,
    load_sources,
    validate_source_catalog,
)
from news_collector.storage.models import WorkflowRun
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.05
RUN_TYPE_SOURCE_CATALOG_RECONCILIATION = "source_catalog_reconciliation"

MutationStatus = Literal[
    "ok",
    "validation_failed",
    "not_found",
    "catalog_locked",
    "db_sync_failed",
    "reconciliation_required",
]


class SourceCatalogMutationRejected(Exception):
    """Raised by a `mutation_fn` to reject the mutation with a typed result.

    The only expected rejection today is "the source id no longer exists in
    the freshly-read catalog" (a delete/toggle racing another writer), which
    maps to the `not_found` status and a 404 at the HTTP layer.
    """


@dataclass(frozen=True)
class SourceCatalogMutationResult:
    """Result of :meth:`SourceCatalogWorkflow.mutate`."""

    status: MutationStatus
    detail: str = ""
    catalog: dict[str, Any] | None = None


class SourceCatalogWorkflow:
    """Owns atomic, serialized mutations of the source catalog."""

    def __init__(
        self,
        db_manager: Any,
        *,
        sources_yaml_path: Path | str | None = None,
        lock_timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.db = db_manager
        self.sources_yaml_path = Path(sources_yaml_path or SOURCES_YAML_PATH)
        # Only the production path owns the in-process ALL_SOURCES globals;
        # an injected path (tests, operator tooling) is isolated by design
        # and must not clobber the module state.
        self._refresh_globals = sources_yaml_path is None
        self.lock_path = self.sources_yaml_path.with_name(
            f"{self.sources_yaml_path.name}.lock"
        )
        self.lock_timeout_seconds = lock_timeout_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Read the current on-disk catalog fresh (no lock, no globals).

        Applies the same `etag`/`last_modified` cache-key defaults
        `load_sources()` applies, so read-only callers see the same shape.
        """
        return self._read_catalog()

    def mutate(
        self,
        mutation_fn: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        db_sync_fn: Callable[[dict[str, Any]], None] | None = None,
    ) -> SourceCatalogMutationResult:
        """Apply one catalog mutation under the advisory lock.

        Sequence: lock → fresh read → apply `mutation_fn` → full-catalog
        validation → atomic write → DB sync (`db_sync_fn`) → release. A DB
        failure restores the prior YAML; a failed restore records a
        `reconciliation_required` marker and says so in the result.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        except OSError as exc:
            logger.error("Source catalog lock file unopenable: {}", exc)
            return SourceCatalogMutationResult(
                "catalog_locked", f"No se pudo abrir el lock del catálogo: {exc}"
            )

        try:
            if not self._acquire_lock(lock_fd):
                return SourceCatalogMutationResult(
                    "catalog_locked",
                    "El catálogo de fuentes está siendo modificado por otra "
                    "operación; inténtalo de nuevo.",
                )
            try:
                return self._mutate_locked(mutation_fn, db_sync_fn)
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            with contextlib.suppress(OSError):
                os.close(lock_fd)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _mutate_locked(
        self,
        mutation_fn: Callable[[dict[str, Any]], dict[str, Any]],
        db_sync_fn: Callable[[dict[str, Any]], None] | None,
    ) -> SourceCatalogMutationResult:
        prior_text = (
            self.sources_yaml_path.read_text(encoding="utf-8")
            if self.sources_yaml_path.exists()
            else ""
        )
        try:
            current = self._parse_catalog(prior_text)
        except (yaml.YAMLError, ValueError) as exc:
            return SourceCatalogMutationResult(
                "validation_failed", f"Catálogo ilegible: {exc}"
            )

        try:
            candidate = mutation_fn(current)
        except SourceCatalogMutationRejected as exc:
            return SourceCatalogMutationResult("not_found", str(exc))

        if not isinstance(candidate, dict):
            return SourceCatalogMutationResult(
                "validation_failed",
                "La mutación no devolvió un catálogo (mapping) válido.",
            )

        errors = validate_source_catalog(candidate)
        if errors:
            return SourceCatalogMutationResult(
                "validation_failed",
                "Catálogo inválido: " + "; ".join(errors[:5]),
                catalog=candidate,
            )

        self._write_text_atomic(self._serialize(candidate))
        self._refresh_in_process_globals()

        if db_sync_fn is None:
            return SourceCatalogMutationResult("ok", catalog=candidate)

        try:
            db_sync_fn(candidate)
        except Exception as exc:  # noqa: BLE001 - any DB failure restores
            logger.error("Source catalog DB sync failed, restoring YAML: {}", exc)
            try:
                self._write_text_atomic(prior_text)
                self._refresh_in_process_globals()
            except Exception as restore_exc:  # noqa: BLE001 - surfaced below
                detail = (
                    "El catálogo quedó inconsistente: la sincronización a la "
                    f"base de datos falló ({exc}) y la restauración del YAML "
                    f"también ({restore_exc})."
                )
                self._record_reconciliation_required(detail, prior_text)
                return SourceCatalogMutationResult("reconciliation_required", detail)
            return SourceCatalogMutationResult(
                "db_sync_failed",
                f"La sincronización a la base de datos falló: {exc}. "
                "El catálogo se restauró a su estado anterior.",
            )

        return SourceCatalogMutationResult("ok", catalog=candidate)

    def _refresh_in_process_globals(self) -> None:
        if self._refresh_globals:
            load_sources()  # keep in-process consumers (ALL_SOURCES) current

    def _read_catalog(self) -> dict[str, Any]:
        if not self.sources_yaml_path.exists():
            return {}
        catalog = self._parse_catalog(
            self.sources_yaml_path.read_text(encoding="utf-8")
        )
        for config in catalog.values():
            if isinstance(config, dict):
                config.setdefault("etag", None)
                config.setdefault("last_modified", None)
        return catalog

    @staticmethod
    def _parse_catalog(text: str) -> dict[str, Any]:
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError("el catálogo no es un mapping de id → configuración")
        return data

    @staticmethod
    def _serialize(catalog: dict[str, Any]) -> str:
        return yaml.safe_dump(
            catalog,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

    def _write_text_atomic(self, text: str) -> None:
        """Same-directory temp file + `os.replace` (the `admin_save_prompts`
        precedent), with an fsync before the replace for durability."""
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.sources_yaml_path.name}-",
            dir=str(self.sources_yaml_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.sources_yaml_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    def _acquire_lock(self, lock_fd: int) -> bool:
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(_LOCK_POLL_SECONDS)

    def _record_reconciliation_required(self, detail: str, prior_text: str) -> None:
        """Persist the inconsistency marker; never let this hide the failure."""
        try:
            with self.db.get_session() as session:
                session.add(
                    WorkflowRun(
                        run_type=RUN_TYPE_SOURCE_CATALOG_RECONCILIATION,
                        status="failed",
                        started_at=datetime.now(timezone.utc),
                        finished_at=datetime.now(timezone.utc),
                        error_code="reconciliation_required",
                        error_detail=detail[:2000],
                        run_metadata={
                            "catalog_path": str(self.sources_yaml_path),
                            "prior_yaml": prior_text,
                        },
                    )
                )
                session.commit()
        except Exception as exc:  # noqa: BLE001 - marker persistence is best-effort
            logger.critical(
                "No se pudo persistir el marcador reconciliation_required ({}): {}",
                exc,
                detail,
            )
