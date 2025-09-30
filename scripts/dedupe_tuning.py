#!/usr/bin/env python
"""SimHash threshold tuning with labeled duplicate sample."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.dedupe import (
    normalize_article_text,
    sha256_hex,
    simhash64,
    hamming_distance,
)


@dataclass
class LabeledPair:
    id: str
    title_a: str
    summary_a: str
    title_b: str
    summary_b: str
    label: int  # 1 duplicate, 0 distinct
    note: str = ""


PAIRS: List[LabeledPair] = [
    LabeledPair(
        "p1",
        "AI breakthrough at MIT",
        "Researchers unveil a new AI model.",
        "AI breakthrough at MIT",
        "Researchers unveil a new AI model.",
        1,
        "Exact duplicate",
    ),
    LabeledPair(
        "p2",
        "AI breakthrough at MIT",
        "Researchers unveil a new AI model.",
        "MIT unveils AI breakthrough",
        "Researchers unveil a new AI model.",
        1,
        "Headline reorder",
    ),
    LabeledPair(
        "p3",
        "NASA discovers new exoplanet",
        "The exoplanet is similar to Earth.",
        "NASA identifies new Earth-like planet",
        "The exoplanet is similar to Earth.",
        1,
        "Paraphrased summary",
    ),
    LabeledPair(
        "p4",
        "COVID-19 vaccine updates",
        "Latest vaccine rollout numbers.",
        "COVID-19 vaccine updates",
        "Latest vaccine rollout statistics released.",
        1,
        "Minor summary variation",
    ),
    LabeledPair(
        "p5",
        "Quantum computing milestone",
        "A major step for quantum supremacy.",
        "Tech stocks rally",
        "Markets react to positive earnings.",
        0,
        "Different topics",
    ),
    LabeledPair(
        "p6",
        "Climate change effects",
        "Wildfires increase across the globe.",
        "Wildfires spread globally",
        "Wildfires increase across the globe.",
        1,
        "Shared theme and content",
    ),
    LabeledPair(
        "p7",
        "New electric car unveiled",
        "The EV features a 500km range.",
        "New electric scooter launched",
        "The scooter offers 100km range.",
        0,
        "Vehicle type differs",
    ),
    LabeledPair(
        "p8",
        "Breakthrough in cancer research",
        "Clinical trials show positive results.",
        "Cancer research breakthrough",
        "Clinical trials show positive results.",
        1,
        "Minor wording change",
    ),
    LabeledPair(
        "p9",
        "Data breach hits major bank",
        "Customer info leaked online.",
        "Major bank suffers data breach",
        "Customer info leaked online.",
        1,
        "Order swapped",
    ),
    LabeledPair(
        "p10",
        "Startup raises Series A",
        "Funding round totals $10M.",
        "Startup raises Series C",
        "Funding round totals $100M.",
        0,
        "Different funding rounds",
    ),
    LabeledPair(
        "p11",
        "Mars rover sends new images",
        "Panorama showcases crater.",
        "Mars rover sends panorama images",
        "Panorama showcases crater.",
        1,
        "Same imagery",
    ),
    LabeledPair(
        "p12",
        "Economic outlook improves",
        "Analysts optimistic for 2026.",
        "Economic outlook worsens",
        "Analysts pessimistic for 2026.",
        0,
        "Opposite sentiment",
    ),
]


def prepare(pair: LabeledPair) -> Tuple[str, str, int, int]:
    _, _, text_a = normalize_article_text(pair.title_a, pair.summary_a)
    _, _, text_b = normalize_article_text(pair.title_b, pair.summary_b)
    sha_a = sha256_hex(text_a)
    sha_b = sha256_hex(text_b)
    sh_a = simhash64(text_a)
    sh_b = simhash64(text_b)
    dist = hamming_distance(sh_a, sh_b)
    return sha_a, sha_b, sh_a, sh_b, dist


def evaluate(threshold: int):
    tp = fp = fn = tn = 0
    false_pos = []
    false_neg = []
    for pair in PAIRS:
        sha_a, sha_b, sh_a, sh_b, dist = prepare(pair)
        exact_dup = sha_a == sha_b
        near_dup = dist <= threshold
        predicted = 1 if (exact_dup or near_dup) else 0
        if predicted == 1 and pair.label == 1:
            tp += 1
        elif predicted == 1 and pair.label == 0:
            fp += 1
            false_pos.append((pair, dist))
        elif predicted == 0 and pair.label == 1:
            fn += 1
            false_neg.append((pair, dist))
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    return {
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "false_pos": false_pos,
        "false_neg": false_neg,
    }


def main():
    results = [evaluate(th) for th in range(4, 17)]
    best = max(results, key=lambda r: r["f1"])
    print("Threshold tuning (SimHash Hamming distance)")
    print("threshold | precision | recall | f1")
    for res in results:
        print(
            f"   {res['threshold']:2d}      {res['precision']:.2f}      {res['recall']:.2f}   {res['f1']:.2f}"
        )

    conf = best["confusion"]
    print("\nRecommended threshold:", best["threshold"])
    print("Confusion matrix (best threshold):")
    print(f"TP={conf['tp']}  FP={conf['fp']}  FN={conf['fn']}  TN={conf['tn']}")

    def format_pair(entry):
        pair, dist = entry
        return f"{pair.id}: dist={dist}, note={pair.note}, titleA='{pair.title_a}', titleB='{pair.title_b}'"

    print("\nTop false positives:")
    for item in best["false_pos"][:10]:
        print("  -", format_pair(item))

    print("\nTop false negatives:")
    for item in best["false_neg"][:10]:
        print("  -", format_pair(item))


if __name__ == "__main__":
    main()
