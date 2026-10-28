"""Corrección automática tras la verificación de respaldo (plan 205).

Cuando el verificador independiente (etapa 7) marca afirmaciones como
``disputed``, este módulo decide sin intervención humana entre dos salidas:

1. El artículo se corrige y se publica: el redactor corrige o elimina los
   datos contradichos, se regeneran titulares y enriquecimiento, y el
   verificador confirma que no queda nada contradicho.
2. El artículo no se publica (``editorial_fact_check_unpublishable``): el
   error contradice el titular o la tesis central, o persiste tras los
   intentos de corrección.

Una falla de infraestructura que impide decidir nunca se convierte en una de
esas dos salidas: conserva el bloqueo reintentable
``editorial_fact_check_disputed``.

Módulo de política: sin red ni E/S. Todas las llamadas a modelos llegan como
hooks del ``EditorAgent``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NoReturn

from news_collector.components.editorial.editorial_publication_artifact import (
    GeneratedArticleValidationError,
)

MAX_FACT_CHECK_CORRECTIONS = 2

UNPUBLISHABLE_ERROR_CODE = "editorial_fact_check_unpublishable"
UNDECIDED_ERROR_CODE = "editorial_fact_check_disputed"


@dataclass(frozen=True)
class DisputedClaim:
    """Afirmación que la fuente contradice, con el motivo del verificador."""

    label: str
    reason: str = ""

    def describe(self) -> str:
        return f"'{self.label}' ({self.reason})" if self.reason else f"'{self.label}'"


@dataclass(frozen=True)
class SeverityJudgement:
    """¿El error contradice lo que promete el titular?

    ``headline_affected`` es ``None`` cuando no se pudo determinar.
    """

    headline_affected: bool | None
    reason: str = ""


@dataclass(frozen=True)
class DerivedArticle:
    """Cuerpo más los campos que se derivan de él (etapas 5 y 6)."""

    content: str
    headlines: dict[str, Any]
    enrichment_fields: dict[str, Any]


@dataclass(frozen=True)
class FactCheckCorrectionHooks:
    """Colaboradores del ``EditorAgent`` que el bucle utiliza."""

    # Etapa 7 sobre una lista de afirmaciones; devuelve las afirmaciones con
    # el estado del verificador.
    verify: Callable[[list[dict]], list[dict]]
    # Motivos del último ``verify``, por ``label``.
    reasons: Callable[[], dict[str, str]]
    judge_severity: Callable[[list[DisputedClaim], dict[str, Any]], SeverityJudgement]
    # Devuelve el cuerpo corregido. Si no puede, lanza una excepción.
    correct: Callable[[str, list[DisputedClaim]], str]
    # Etapas 5 y 6 sobre el cuerpo corregido.
    rederive: Callable[[str], DerivedArticle]
    # ¿El cuerpo sigue sosteniendo la afirmación? ``None`` = no concluyente.
    still_asserted: Callable[[str, DisputedClaim], bool | None]


@dataclass(frozen=True)
class FactCheckCorrectionOutcome:
    article: DerivedArticle
    verified_fact_check: list[dict]
    record: dict[str, Any] = field(default_factory=dict)

    @property
    def corrected(self) -> bool:
        return bool(self.record.get("attempts"))


def disputed_claims(
    verified_fact_check: list[Any], reasons: dict[str, str]
) -> list[DisputedClaim]:
    """Afirmaciones con estado ``disputed``, en orden y sin duplicados."""
    seen: set[str] = set()
    result: list[DisputedClaim] = []
    for item in verified_fact_check:
        if not isinstance(item, dict) or item.get("status") != "disputed":
            continue
        label = str(item.get("label", "")).strip() or "(sin descripción)"
        if label in seen:
            continue
        seen.add(label)
        result.append(DisputedClaim(label, reasons.get(label, "")))
    return result


def _labels(claims: list[DisputedClaim]) -> list[str]:
    return [claim.label for claim in claims]


def _raise_with_record(
    message: str, error_code: str, record: dict[str, Any]
) -> NoReturn:
    error = GeneratedArticleValidationError(message, error_code=error_code)
    # The caller persists the trace even when the decision is negative (A8).
    error.correction_record = record  # type: ignore[attr-defined]
    raise error


def _unpublishable(message: str, record: dict[str, Any]) -> NoReturn:
    record["decision"] = "unpublishable"
    _raise_with_record(f"No se publica: {message}", UNPUBLISHABLE_ERROR_CODE, record)


def _undecided(message: str, record: dict[str, Any]) -> NoReturn:
    record["decision"] = "undecided"
    _raise_with_record(
        f"Verificación sin decisión (se reintentará): {message}",
        UNDECIDED_ERROR_CODE,
        record,
    )


def _decide_before_correcting(
    pending: list[DisputedClaim],
    severity: SeverityJudgement,
    attempt: int,
    max_corrections: int,
    record: dict[str, Any],
) -> None:
    """Rechazo definitivo, bloqueo reintentable o permiso para corregir."""
    record.setdefault("severity", []).append(
        {
            "claims": _labels(pending),
            "headline_affected": severity.headline_affected,
            "reason": severity.reason,
        }
    )
    described = "; ".join(claim.describe() for claim in pending)
    if severity.headline_affected is True:
        _unpublishable(
            "la fuente contradice lo que afirma el titular. "
            f"Afirmaciones contradichas: {described}. "
            f"Motivo: {severity.reason or 'sin detalle'}",
            record,
        )
    if severity.headline_affected is None:
        _undecided(
            "no se pudo evaluar si las afirmaciones contradichas "
            f"{_labels(pending)} afectan al titular. Detalle: "
            f"{severity.reason or 'sin respuesta válida del verificador'}",
            record,
        )
    if attempt >= max_corrections:
        _unpublishable(
            f"tras {max_corrections} intento(s) de corrección la fuente "
            f"sigue contradiciendo el artículo: {described}",
            record,
        )


def _correct_or_undecided(
    hooks: FactCheckCorrectionHooks,
    content: str,
    pending: list[DisputedClaim],
    record: dict[str, Any],
) -> str:
    try:
        return hooks.correct(content, pending)
    except GeneratedArticleValidationError as exc:
        _undecided(f"la corrección automática falló: {exc}", record)
    except Exception as exc:  # cualquier fallo del redactor es infraestructura
        _undecided(
            f"la corrección automática falló ({type(exc).__name__}: {exc})",
            record,
        )


def _residual_check(
    hooks: FactCheckCorrectionHooks,
    content: str,
    pending: list[DisputedClaim],
    history: dict[str, DisputedClaim],
) -> list[str]:
    """Añade a ``pending`` lo que el cuerpo corregido aún sostiene.

    Devuelve las afirmaciones cuyo control no fue concluyente.
    """
    pending_labels = set(_labels(pending))
    inconclusive: list[str] = []
    for claim in history.values():
        if claim.label in pending_labels:
            continue
        asserted = hooks.still_asserted(content, claim)
        if asserted is True:
            pending.append(claim)
            pending_labels.add(claim.label)
        elif asserted is None:
            inconclusive.append(claim.label)
    return inconclusive


def run_fact_check_correction(
    article: DerivedArticle,
    verified_fact_check: list[dict],
    hooks: FactCheckCorrectionHooks,
    *,
    max_corrections: int = MAX_FACT_CHECK_CORRECTIONS,
) -> FactCheckCorrectionOutcome:
    """Corrige el artículo o decide que no se publica.

    Sin afirmaciones ``disputed`` devuelve la entrada sin llamar a ningún
    hook. Lanza ``GeneratedArticleValidationError`` con
    ``UNPUBLISHABLE_ERROR_CODE`` (decisión definitiva) o
    ``UNDECIDED_ERROR_CODE`` (infraestructura; reintentable).
    """
    pending = disputed_claims(verified_fact_check, hooks.reasons())
    record: dict[str, Any] = {"decision": "clean", "attempts": []}
    if not pending:
        return FactCheckCorrectionOutcome(article, verified_fact_check, record)

    # Todas las afirmaciones contradichas vistas: el control residual exige
    # que ninguna siga presente en el cuerpo final.
    history: dict[str, DisputedClaim] = {claim.label: claim for claim in pending}
    current = article
    record["initial_disputed"] = [
        {"label": claim.label, "reason": claim.reason} for claim in pending
    ]

    for attempt in range(max_corrections + 1):
        severity = hooks.judge_severity(pending, current.headlines)
        _decide_before_correcting(pending, severity, attempt, max_corrections, record)

        corrected_body = _correct_or_undecided(hooks, current.content, pending, record)
        try:
            current = hooks.rederive(corrected_body)
            current_verified = hooks.verify(
                list(current.enrichment_fields.get("fact_check") or [])
            )
        except Exception as exc:  # etapas 5-6 sobre el cuerpo corregido
            _undecided(
                "falló la regeneración de titulares o enriquecimiento tras la "
                f"corrección ({type(exc).__name__}: {exc})",
                record,
            )
        pending = disputed_claims(current_verified, hooks.reasons())
        for claim in pending:
            history.setdefault(claim.label, claim)
        inconclusive = _residual_check(hooks, current.content, pending, history)

        record["attempts"].append(
            {
                "attempt": attempt + 1,
                "addressed": list(history),
                "remaining_disputed": _labels(pending),
                "residual_inconclusive": inconclusive,
            }
        )
        if pending:
            continue
        if inconclusive:
            _undecided(
                "no se pudo confirmar que el texto corregido ya no "
                f"sostiene: {inconclusive}",
                record,
            )
        record["decision"] = "corrected"
        return FactCheckCorrectionOutcome(current, current_verified, record)

    raise AssertionError("unreachable: the loop always returns or raises")
