"""Plan 205: bucle de corrección automática tras la verificación de respaldo.

Cubre cada rama de ``run_fact_check_correction`` con hooks falsos
deterministas: el módulo es política pura, sin red.
"""

from __future__ import annotations

from typing import Any

import pytest

from news_collector.components.editorial.editorial_publication_artifact import (
    GeneratedArticleValidationError,
)
from news_collector.components.editorial.fact_check_correction import (
    UNDECIDED_ERROR_CODE,
    UNPUBLISHABLE_ERROR_CODE,
    DerivedArticle,
    DisputedClaim,
    FactCheckCorrectionHooks,
    SeverityJudgement,
    disputed_claims,
    run_fact_check_correction,
)

WRONG = "Solo 14 de 89 diseños tenían actividad residual"
WRONG_2 = "La evolución dirigida in silico mejoró la actividad"
OK = "Modelar el agua mejora el diseño de enzimas"


def _article(content: str = "cuerpo original", claims=None) -> DerivedArticle:
    return DerivedArticle(
        content=content,
        headlines={"direct": "Modelar el agua mejora el diseño de enzimas"},
        enrichment_fields={"fact_check": claims or []},
    )


class FakeHooks:
    """Hooks configurables que registran cada llamada."""

    def __init__(
        self,
        *,
        severity: list[SeverityJudgement] | None = None,
        verdicts: list[dict[str, str]] | None = None,
        residual: dict[str, bool | None] | None = None,
        correct_error: Exception | None = None,
        reasons: dict[str, str] | None = None,
    ) -> None:
        self.severity = list(severity or [SeverityJudgement(False, "secundario")])
        # Un dict de label -> status por cada llamada a verify tras corregir.
        self.verdicts = list(verdicts or [])
        self.residual = residual or {}
        self.correct_error = correct_error
        self._reasons = reasons or {WRONG: "La fuente dice 3 de 89"}
        self.calls: list[tuple[str, Any]] = []
        self.corrections = 0

    def verify(self, claims: list[dict]) -> list[dict]:
        self.calls.append(("verify", [c["label"] for c in claims]))
        statuses = self.verdicts.pop(0) if self.verdicts else {}
        return [{**c, "status": statuses.get(c["label"], "confirmed")} for c in claims]

    def reasons(self) -> dict[str, str]:
        return self._reasons

    def judge_severity(self, claims, headlines) -> SeverityJudgement:
        self.calls.append(("severity", [c.label for c in claims]))
        return self.severity.pop(0) if len(self.severity) > 1 else self.severity[0]

    def correct(self, content: str, claims) -> str:
        self.calls.append(("correct", [c.label for c in claims]))
        if self.correct_error is not None:
            raise self.correct_error
        self.corrections += 1
        return f"cuerpo corregido {self.corrections}"

    def rederive(self, content: str) -> DerivedArticle:
        self.calls.append(("rederive", content))
        return _article(content, [{"label": OK, "status": "needs_review"}])

    def still_asserted(self, content: str, claim: DisputedClaim) -> bool | None:
        self.calls.append(("residual", claim.label))
        return self.residual.get(claim.label, False)

    def hooks(self) -> FactCheckCorrectionHooks:
        return FactCheckCorrectionHooks(
            verify=self.verify,
            reasons=self.reasons,
            judge_severity=self.judge_severity,
            correct=self.correct,
            rederive=self.rederive,
            still_asserted=self.still_asserted,
        )

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def _disputed(*labels: str) -> list[dict]:
    return [{"label": label, "status": "disputed"} for label in labels] + [
        {"label": OK, "status": "confirmed"}
    ]


def test_clean_verification_returns_input_without_calling_hooks() -> None:
    fake = FakeHooks()
    article = _article()
    verified = [{"label": OK, "status": "confirmed"}]

    outcome = run_fact_check_correction(article, verified, fake.hooks())

    assert outcome.article is article
    assert outcome.verified_fact_check is verified
    assert outcome.corrected is False
    assert outcome.record["decision"] == "clean"
    assert fake.calls == []


def test_headline_affected_is_terminal_and_never_corrects() -> None:
    fake = FakeHooks(severity=[SeverityJudgement(True, "El titular promete X")])

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_fact_check_correction(_article(), _disputed(WRONG), fake.hooks())

    assert excinfo.value.error_code == UNPUBLISHABLE_ERROR_CODE
    assert "titular" in str(excinfo.value)
    assert WRONG in str(excinfo.value)
    assert "La fuente dice 3 de 89" in str(excinfo.value)
    assert "correct" not in fake.names()


def test_undeterminable_severity_is_retryable_not_terminal() -> None:
    fake = FakeHooks(severity=[SeverityJudgement(None, "timeout")])

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_fact_check_correction(_article(), _disputed(WRONG), fake.hooks())

    assert excinfo.value.error_code == UNDECIDED_ERROR_CODE
    assert "correct" not in fake.names()


def test_secondary_error_is_corrected_and_published() -> None:
    fake = FakeHooks()

    outcome = run_fact_check_correction(
        _article(), _disputed(WRONG, WRONG_2), fake.hooks()
    )

    assert outcome.corrected is True
    assert outcome.record["decision"] == "corrected"
    assert outcome.article.content == "cuerpo corregido 1"
    assert outcome.verified_fact_check == [{"label": OK, "status": "confirmed"}]
    # La corrección recibe ambas afirmaciones; el residual revisa ambas.
    assert ("correct", [WRONG, WRONG_2]) in fake.calls
    assert ("residual", WRONG) in fake.calls
    assert ("residual", WRONG_2) in fake.calls
    assert outcome.record["initial_disputed"][0] == {
        "label": WRONG,
        "reason": "La fuente dice 3 de 89",
    }


def test_second_attempt_can_succeed() -> None:
    fake = FakeHooks(verdicts=[{OK: "disputed"}, {}])

    outcome = run_fact_check_correction(_article(), _disputed(WRONG), fake.hooks())

    assert fake.corrections == 2
    assert outcome.article.content == "cuerpo corregido 2"
    assert len(outcome.record["attempts"]) == 2
    # Tras el 1.er intento, la afirmación nueva se juzga antes de corregir otra vez.
    assert fake.names().count("severity") == 2


def test_persistent_dispute_after_max_attempts_is_terminal() -> None:
    fake = FakeHooks(verdicts=[{OK: "disputed"}, {OK: "disputed"}])

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_fact_check_correction(_article(), _disputed(WRONG), fake.hooks())

    assert excinfo.value.error_code == UNPUBLISHABLE_ERROR_CODE
    assert "2 intento(s)" in str(excinfo.value)
    assert fake.corrections == 2


def test_residual_check_catches_claim_omitted_from_new_fact_check() -> None:
    """El fact_check regenerado ya no lista el dato erróneo, pero el cuerpo
    corregido lo sigue afirmando: no basta para publicar."""
    fake = FakeHooks(residual={WRONG: True})

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_fact_check_correction(_article(), _disputed(WRONG), fake.hooks())

    assert excinfo.value.error_code == UNPUBLISHABLE_ERROR_CODE
    assert fake.corrections == 2


def test_inconclusive_residual_is_retryable() -> None:
    fake = FakeHooks(residual={WRONG: None})

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_fact_check_correction(_article(), _disputed(WRONG), fake.hooks())

    assert excinfo.value.error_code == UNDECIDED_ERROR_CODE
    assert WRONG in str(excinfo.value)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("provider down"),
        GeneratedArticleValidationError("técnica", error_code="E_X"),
    ],
)
def test_corrector_failure_is_retryable(error: Exception) -> None:
    fake = FakeHooks(correct_error=error)

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_fact_check_correction(_article(), _disputed(WRONG), fake.hooks())

    assert excinfo.value.error_code == UNDECIDED_ERROR_CODE
    assert "rederive" not in fake.names()


def test_headline_affected_on_second_round_is_terminal() -> None:
    fake = FakeHooks(
        severity=[SeverityJudgement(False), SeverityJudgement(True, "nuevo titular")],
        verdicts=[{OK: "disputed"}],
    )

    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        run_fact_check_correction(_article(), _disputed(WRONG), fake.hooks())

    assert excinfo.value.error_code == UNPUBLISHABLE_ERROR_CODE
    assert fake.corrections == 1


def test_disputed_claims_dedupes_and_ignores_malformed_items() -> None:
    claims = disputed_claims(
        [
            {"label": WRONG, "status": "disputed"},
            {"label": WRONG, "status": "disputed"},
            {"label": "", "status": "disputed"},
            {"label": OK, "status": "confirmed"},
            "no es un dict",
        ],
        {WRONG: "motivo"},
    )

    assert claims == [
        DisputedClaim(WRONG, "motivo"),
        DisputedClaim("(sin descripción)", ""),
    ]
