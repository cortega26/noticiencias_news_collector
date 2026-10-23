# Held candidate review packet

This literal view preserves the archived packet as data. Human review remains pending.
The captured text is not rendered as Markdown or HTML.

Raw archived bytes: [candidate-trial4-review-packet.raw.txt](candidate-trial4-review-packet.raw.txt)

SHA-256: `f44eb8c6d803388402de16d984dd62a8de6bd2c74a2fdf2927508a6689b0b383`

The raw artifact preserves every byte previously archived at `candidate-trial4-review-packet.md`.
It remains a reconstruction from the retained
[execution report](candidate-trial4-chain-report.json) and stage cache,
with the [held draft](candidate-trial4-held-draft.md) retained separately.
It is not a completed candidate draft or editorial approval.

````text
# Held candidate — human review pending

This packet was reconstructed from the retained execution report and stage cache after the bounded run. It is not a completed editorial draft or approval.

Source: https://science.nasa.gov/blogs/webb/2024/06/05/reconnaissance-of-potentially-habitable-worlds-with-nasas-webb/

Partial source coverage: summary_only. The retained source and stage-2 draft are adjacent artifacts. The attempted repair failed technical revalidation; it did not clear the recorded close-paraphrase finding.

{
  "label": "candidate",
  "calls": 6,
  "elapsed_seconds": 148.57,
  "last_stage": "technical_critic_or_source_support",
  "error": "GeneratedArticleValidationError at technical_critic_or_source_support: E_EDITORIAL_REPAIR_TECHNICAL: La reparación editorial no supera revisión técnica; borrador pendiente.",
  "output_chars": 0,
  "critic_verdict": {
    "approved": false,
    "average": 8.0,
    "scores": {
      "hook_score": 8,
      "clarity_score": 9,
      "structure_score": 8,
      "rigor_score": 7,
      "voice_score": 9,
      "shareability_score": 8,
      "closing_score": 7
    },
    "value_add_assessment": "close_paraphrase",
    "value_add_evidence": "El texto reproduce casi palabra por palabra el contenido y la estructura del material fuente, sin aportar análisis, contexto adicional ni síntesis crítica.",
    "material_claims_supported": true,
    "support_issues": [],
    "verification_status": "reviewed",
    "reviewed_content_sha256": "1618cff19270901341eedf8317d3fe916d68a93c1dd98fe1d66bf35927563558"
  },
  "headline_verdict": {
    "approved": false,
    "verification_status": "unverified"
  },
  "source_support_verdict": null,
  "human_review": {
    "status": "pending",
    "reviewer": null
  }
}
````
