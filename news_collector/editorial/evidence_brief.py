"""Bounded, source-derived editorial context; no retrieval or factual certification.

The passages are exact available text, not an invented primary-source summary.
The planning question and proposed contribution are assignments, not findings.
"""

from __future__ import annotations

from dataclasses import dataclass

from news_collector.editorial.draft_identity import editorial_text_sha256


@dataclass(frozen=True)
class EvidenceBrief:
    reader_question: str
    proposed_contribution: str
    source_url: str
    source_sha256: str
    coverage: str
    passage: str
    truncated: bool

    def markdown(self) -> str:
        coverage = {
            "full_text": "Texto disponible marcado como completo por la ingesta",
            "summary_only": "Solo resumen: detalles del texto completo no comprobados",
            "summary_fallback": "Resumen de respaldo: detalles no comprobados",
        }.get(self.coverage, "Cobertura no especificada; no asumir texto completo")
        return (
            "## Brief de evidencia (interno, revisión humana pendiente)\n\n"
            f"Pregunta del lector: {self.reader_question}\n\n"
            f"Aporte propuesto, pendiente de comprobar: {self.proposed_contribution}\n\n"
            f"Fuente disponible: {self.source_url or 'URL no disponible'}\n"
            f"SHA-256 de fuente: `{self.source_sha256}`\n"
            f"Cobertura: {coverage}. "
            "No se recuperaron fuentes adicionales; independencia y fuente primaria "
            "no verificadas. Una noticia que cita un estudio no es el estudio.\n\n"
            "Pasaje literal disponible "
            f"({'extracto truncado' if self.truncated else 'texto íntegro'}):\n\n"
            f"{self.passage}\n\n"
            "Respaldo de afirmaciones: pendiente de comparación del borrador final. "
            "La coincidencia con esta fuente no es corroboración independiente."
        )


def build_evidence_brief(
    *, title: str, source_url: str, source_content: str, content_mode: str
) -> EvidenceBrief:
    """Create a planning brief using only text already available to the editor."""
    return EvidenceBrief(
        reader_question=(
            f"¿Qué permite concluir la evidencia disponible sobre «{title}» "
            "y qué queda por resolver?"
        ),
        proposed_contribution=(
            "Explicar el hallazgo y su alcance; separar observación, interpretación "
            "e incertidumbre. No añadir aplicaciones ni contexto sin respaldo."
        ),
        source_url=source_url,
        source_sha256=editorial_text_sha256(source_content),
        coverage=content_mode,
        passage=source_content[:3000],
        truncated=len(source_content) > 3000,
    )
