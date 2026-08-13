#!/usr/bin/env python3
"""Plan 048 Step 2/3 execution: review and label the enrichment corpus.

Applies independent editorial judgment to each of the 44 records:
gold_topics/gold_entities are decided from title+summary ONLY (per the
corpus spec), treating model_draft_* as reference, never authority.

This is a SINGLE automated reviewer pass. The plan's Step 2 asks for two
independent human reviewers with adjudication; that bar is not met by
this pass and the ADR/ledger record that honestly. A light self-check
(re-labeling ~10% blind) is done in the accompanying test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CORPUS = (
    Path(__file__).resolve().parents[1] / "tests" / "data" / "enrichment_eval.jsonl"
)

# id -> (gold_topics, gold_entities, reviewer_note)
GOLD = {
    # --- positive cases ---
    "en-space-pos-001": (
        ["space", "science"],
        ["NASA", "Orion"],
        "Lunar mission NASA: space dominant; science from space research. "
        "technology NOT inferable from title+summary (no tech mentioned).",
    ),
    "es-space-pos-002": (["space", "science"], ["NASA"], "Lunar launch window NASA."),
    "pt-space-pos-003": (["space", "science"], ["ESA"], "Orbital rocket ESA."),
    "fr-space-pos-004": (
        ["space", "science"],
        ["Agence spatiale europeenne", "Ariane 6"],
        "Lunar flight + Ariane 6.",
    ),
    "en-science-pos-005": (
        ["science", "health"],
        [],
        "Cell regeneration study: science dominant; health from the medical angle.",
    ),
    "es-science-pos-006": (
        ["science"],
        ["Universidad Nacional Autonoma de Mexico"],
        "Peer-reviewed scientific study.",
    ),
    "pt-science-pos-007": (
        ["science"],
        ["Universidade de Sao Paulo"],
        "Peer-reviewed research.",
    ),
    "fr-science-pos-008": (["science"], [], "Scientific study marine biodiversity."),
    "en-health-pos-009": (["health"], [], "Flu cases decline: health."),
    "es-health-neg-010": (
        ["health"],
        ["Ministerio de Salud de Chile"],
        "Respiratory cases rise: health. science NOT inferable (ministerial report, not a study).",
    ),
    "pt-health-pos-011": (
        ["health"],
        ["Ministerio da Saude"],
        "Flu vaccination campaign.",
    ),
    "fr-health-pos-012": (["health"], [], "Vaccination campaign flu."),
    "en-tech-pos-013": (
        ["technology"],
        [],
        "AI translation tool: technology. science NOT (product, not study).",
    ),
    "es-tech-pos-014": (["technology"], ["Telefonica"], "Tech platform for cities."),
    "pt-tech-pos-015": (
        ["technology"],
        [],
        "AI research tool: technology. science NOT (not a study).",
    ),
    "fr-tech-pos-016": (
        ["technology"],
        [],
        "Scientific tool: technology (a tool). science NOT (not research).",
    ),
    "en-climate-pos-017": (["climate"], [], "Climate resilience plan."),
    "es-climate-pos-018": (
        ["climate", "technology"],
        ["Universidad Nacional Autonoma de Mexico"],
        "Clean-tech climate solutions: climate dominant; technology from the tech solution.",
    ),
    "pt-climate-pos-019": (
        ["climate", "science"],
        ["Universidade de Sao Paulo", "Amazonia"],
        "Satellite climate monitoring Amazon: climate+science (scientific monitoring).",
    ),
    "fr-climate-pos-020": (
        ["climate"],
        [],
        "Glacier melt report: climate. science NOT (report, not study).",
    ),
    "en-economy-pos-021": (["economy"], ["IMF"], "Global growth projection."),
    "es-economy-pos-022": (["economy"], ["FMI"], "Inflation risks emerging markets."),
    "pt-economy-pos-023": (["economy"], ["FMI"], "Economic growth."),
    "fr-economy-pos-024": (["economy"], ["FMI"], "Inflation risks."),
    # --- general_fallback ---
    "en-general-025": (
        ["general"],
        [],
        "Local cultural festival: no scientific topic.",
    ),
    "es-general-026": (["general"], [], "Cultural festival."),
    "pt-general-027": (["general"], [], "Cultural festival."),
    "fr-general-028": (["general"], [], "Local cultural festival."),
    "es-general-heldout-043": (["general"], [], "Neighborhood crafts fair."),
    "pt-general-heldout-044": (["general"], [], "Neighborhood crafts fair."),
    # --- adversarial ---
    "pt-adversarial-ia-case-029": (
        ["general"],
        [],
        "'ia' is the verb form (iba a / was going to), NOT the AI acronym -> general.",
    ),
    "es-adversarial-substring-030": (
        ["health"],
        [],
        "'nasal' contains 'nasa' but is NOT NASA: health from congestion. "
        "Tests that substring entity matching must NOT fire.",
    ),
    "en-adversarial-negation-031": (
        ["space"],
        ["NASA"],
        "Explicit negation but the TOPIC space persists (lunar subject); NASA is "
        "present as entity. Tests that negation does not drop the subject's topic.",
    ),
    "fr-adversarial-accent-032": (
        ["space"],
        ["Agence spatiale europeenne", "Ariane 6"],
        "Accentless 'europeenne' must match the same: space from launcher. "
        "Entity normalized to accentless form as it appears in the text.",
    ),
    "es-adversarial-multitopic-033": (
        ["science", "climate", "technology", "economy"],
        [],
        "Climate study + AI + economists: 4 legitimate topics from the text.",
    ),
    "en-adversarial-hardneg-034": (
        ["general"],
        [],
        "Bakery competition: no topic -> general.",
    ),
    "pt-adversarial-hardneg-035": (["general"], [], "Soccer: no topic -> general."),
    "fr-adversarial-hardneg-036": (["general"], [], "Pastry: no topic -> general."),
    # --- heldout positives ---
    "en-space-heldout-037": (
        ["space", "science"],
        [],
        "Satellite orbit insertion: space+science (science payload).",
    ),
    "es-health-heldout-038": (
        ["health"],
        ["Ministerio de Salud de Chile"],
        "Winter vaccination campaign.",
    ),
    "pt-tech-heldout-039": (
        ["technology", "science"],
        ["Universidade de Sao Paulo"],
        "Solar energy tech + university research: technology+science.",
    ),
    "fr-economy-heldout-040": (["economy"], [], "Regional economic recovery."),
    "es-adversarial-negation-041": (
        ["economy"],
        ["FMI"],
        "Negated (no recession) but economy topic persists (economic subject).",
    ),
    "en-adversarial-multitopic-042": (
        ["technology", "health", "climate", "science", "economy"],
        [],
        "Exactly 5 topics from the text (the cap).",
    ),
}


def main() -> int:
    rows = [
        json.loads(line) for line in CORPUS.read_text().splitlines() if line.strip()
    ]
    by_id = {r["id"]: r for r in rows}
    missing = [rid for rid in GOLD if rid not in by_id]
    extra = [rid for rid in by_id if rid not in GOLD]
    if missing:
        print(f"GOLD has ids not in corpus: {missing}")
        return 1
    if extra:
        print(f"Corpus has ids not in GOLD (unlabeled): {extra}")
        return 1

    out = []
    for r in rows:
        gold_topics, gold_entities, note = GOLD[r["id"]]
        r["gold_topics"] = gold_topics
        r["gold_entities"] = gold_entities
        r["review_status"] = "reviewed"
        r["reviewer_notes"] = note
        out.append(r)

    CORPUS.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out),
        encoding="utf-8",
    )
    print(f"Labeled {len(out)} records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
