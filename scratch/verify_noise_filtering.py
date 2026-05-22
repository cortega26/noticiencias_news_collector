#!/usr/bin/env python3
"""Verification script for LatAm relevance filtering and noise suppression."""

import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_collector.scoring.cognitive_scorer import CognitiveScorer
from news_collector.scoring.heuristic_scorer import HeuristicScorer
from news_collector.scoring.latam_relevance import score_candidate_for_latam_audience
from news_collector.storage.models import Article

# Test articles
TEST_ARTICLES = [
    {
        "id": "art_aws_tutorial",
        "title": "How to deploy a FastAPI application on AWS SageMaker and Bedrock",
        "summary": "This tutorial shows how to deploy Python models on Amazon Web Services using SageMaker endpoints and Bedrock APIs, configuring API Gateway and Lambda.",
        "content": "Step 1: Create an AWS account. Step 2: Configure SageMaker permissions. Step 3: Run your deploy commands using our SDK. Make sure to set up API Gateway routes to handle requests.",
        "category": "Corporate Dev Tutorial (Noise)",
        "expected_action": "DISCARD (Capped at 0.55)",
    },
    {
        "id": "art_us_politics",
        "title": "US Senate Debates Supreme Court Ruling on Abortion Pill and Mifepristone",
        "summary": "Senate Democrats and GOP members sparred on Capitol Hill today over the Biden administration's stance on abortion access and mifepristone regulations.",
        "content": "The hearing featured heated exchanges between partisan candidates regarding the electoral implications of the recent ruling, with the governor expressing deep concerns.",
        "category": "US Domestic Politics (Noise)",
        "expected_action": "DISCARD (Capped at 0.55)",
    },
    {
        "id": "art_cs_preprint",
        "title": "OOD Generalization and Sparse Autoencoders in Transformer Architectures (arXiv:2605.1234)",
        "summary": "We present a mathematical proof showing how out-of-distribution (OOD) generalization improves when using sparse autoencoders to study mechanistic interpretability.",
        "content": "Here we define Theorem 1.1 on inference scaling behavior. Our proofs assume a standard transformer architecture with mechanistic interpretability constraints.",
        "category": "Academic CS Preprint (Noise)",
        "expected_action": "DISCARD (Capped at 0.55)",
    },
    {
        "id": "art_latam_science",
        "title": "UNAM and CONICET 2026 Study Reveals 25% Shift in Amazon Biodiversity Patterns",
        "summary": "Mexican and Argentine scientists map 45 new species in the rainforest under climate stress.",
        "content": "Researchers from UNAM (Mexico) and CONICET (Argentina) published a joint study analyzing climate change effects on biodiversity in the Amazon basin, noting a significant 15% shift in animal migrations.",
        "category": "LatAm Science (Target)",
        "expected_action": "PUBLISH/PRIORITY (Passed Relevance)",
    },
    {
        "id": "art_global_science",
        "title": "James Webb Space Telescope Discovers New Exoplanet in Habitable Zone",
        "summary": "Astronomers identify a rocky planet with atmospheric water vapor 100 light years away.",
        "content": "A study published by an international team of scientists reports the detection of water vapor signatures in the atmosphere of a newly discovered planet.",
        "category": "Global Science (Target)",
        "expected_action": "PUBLISH/PRIORITY (Passed Relevance)",
    },
]


def main():
    print("=" * 90)
    print("VERIFYING LATAM RELEVANCE & NOISE SUPPRESSION SCORING")
    print("=" * 90)

    heuristic_scorer = HeuristicScorer()
    # Initialize CognitiveScorer with None client to test mock finalization
    cognitive_scorer = CognitiveScorer(llm_client=object())

    for art_dict in TEST_ARTICLES:
        print(f"\nTitle: {art_dict['title']}")
        print(f"Category: {art_dict['category']}")
        print(f"Expected Action: {art_dict['expected_action']}")
        print("-" * 50)

        # 1. Candidate score (Ingestion phase helper)
        cand_score = score_candidate_for_latam_audience(art_dict)
        print(f"Pre-Scorer Candidate Score: {cand_score:.2f}")

        # Construct Article object for scoring
        art_obj = Article(
            id=art_dict["id"],
            title=art_dict["title"],
            summary=art_dict["summary"],
            content=art_dict["content"],
            url=f"http://example.com/{art_dict['id']}",
            source_id="verify_source",
            published_date=datetime.now(timezone.utc),
        )

        # 2. Heuristic Scorer score
        h_score = heuristic_scorer.calculate_score(art_obj)
        print(f"Heuristic Scorer Score: {h_score:.4f}")

        # 3. Finalize score under Heuristic mode (uses the same deterministic logic for relevance)
        res_heuristic = {
            "score": h_score,
            "details": {"heuristic": True},
            "reasoning": "Heuristic validation",
        }
        final_res = cognitive_scorer._finalize_score(
            art_obj,
            res_heuristic,
            source_config={"url": "http://example.com"},
            is_heuristic=True,
        )

        final_score = final_res["final_score"]
        should_inc = final_res["should_include"]
        dec_label = final_res["decision_label"]
        nqi_rel = final_res["components"]["nqi_relevance"]

        print(f"Final Combined NQI Score: {final_score:.4f}")
        print(f"Relevance Component Score: {nqi_rel:.4f}")
        print(f"Decision: {dec_label.upper()} (Include: {should_inc})")

        # Verify the assertion for this article
        if "DISCARD" in art_dict["expected_action"]:
            if final_score <= 0.55 and not should_inc and dec_label == "discard":
                print("\033[92m[PASS] Noise correctly suppressed.\033[0m")
            else:
                print("\033[91m[FAIL] Noise leaked or scored too high!\033[0m")
        else:
            if (
                final_score >= 0.60
                and should_inc
                and dec_label in ("publishable", "priority")
            ):
                print("\033[92m[PASS] Target science story passed.\033[0m")
            else:
                print(
                    "\033[91m[FAIL] Target story did not pass validation threshold!\033[0m"
                )

    print("\n" + "=" * 90)
    print("Verification Completed.")
    print("=" * 90)


if __name__ == "__main__":
    main()
