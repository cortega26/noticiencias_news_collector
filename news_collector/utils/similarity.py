"""Near-duplicate grouping over title+summary (Plan 111, Step 2).

Word+bigram TF cosine, standard library only — no vector DB, no embedding
stack (plan 080 defers sentence-transformers until a labeled benchmark
exists; this module must not smuggle one in). MinHash was measured and
rejected for this job: it scores exact n-gram overlap, so genuine
cross-outlet paraphrases of one finding score ~0.0 while unigram+bigram
cosine separates them cleanly (paraphrase ~0.40, distinct topics ~0.0,
near-identical ~0.79 on the golden pair).

Deterministic: same input order and threshold always yield the same
groups, so per-page triage grouping is stable across requests.

Scope: runtime grouping for the triage queue (small N per page), not a
replacement for the simhash ingestion dedup in `dedupe.py`, which owns
exact-duplicate clustering at write time. Cross-language paraphrase is
explicitly out of scope (disjoint vocabularies).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from math import sqrt

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
# Measured separation on golden pairs (see tests/unit/utils/test_similarity):
# paraphrase ~0.34-0.40, same-topic-different-finding ~0.05, distinct ~0.0,
# near-identical ~0.79. 0.30 keeps margin on both sides.
_DEFAULT_THRESHOLD = 0.30


@dataclass(frozen=True)
class SimilarGroup:
    """One near-duplicate group. `master_id` is the first member in input
    order — callers pass ranked order so the master is the highest-scored
    candidate editors should keep."""

    group_id: str
    master_id: int
    member_ids: tuple[int, ...] = ()
    confidence: float = 0.0


def _features(text: object) -> Counter[str]:
    """Unigram + bigram term frequencies over normalized tokens."""
    tokens = _TOKEN_RE.findall(str(text or "").lower())
    feats: Counter[str] = Counter(tokens)
    feats.update(" ".join(tokens[i : i + 2]) for i in range(len(tokens) - 1))
    return feats


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(count * right.get(term, 0) for term, count in left.items())
    if not dot:
        return 0.0
    norm = sqrt(sum(v * v for v in left.values())) * sqrt(
        sum(v * v for v in right.values())
    )
    return dot / norm if norm else 0.0


def _document_text(item: dict) -> str:
    return f"{item.get('title') or ''}\n{item.get('summary') or ''}"


def _parse_id(item: object) -> int | None:
    """Article id as int, or None for missing/unparseable ids (never raises)."""
    if not isinstance(item, dict):
        return None
    raw = item.get("id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _cluster_positions(
    vectors: dict[int, Counter[str]],
    order: list[int],
    threshold: float,
) -> list[list[int]]:
    """Union-find over pairs at or above threshold; clusters of size >= 2."""
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        root = parent.setdefault(node, node)
        while parent[root] != root:
            parent[root] = parent[parent[root]]
            root = parent[root]
        return root

    for i in range(len(order)):
        for j in range(i + 1, len(order)):
            left, right = order[i], order[j]
            if _cosine(vectors[left], vectors[right]) < threshold:
                continue
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

    clusters: dict[int, list[int]] = {}
    for position in order:
        clusters.setdefault(find(position), []).append(position)
    return [members for members in clusters.values() if len(members) >= 2]


def _group_fingerprint(member_ids: tuple[int, ...]) -> str:
    """Deterministic group id (non-security use: UI correlation only)."""
    return (
        "sim-"
        + hashlib.sha256(
            ",".join(str(mid) for mid in sorted(member_ids)).encode()
        ).hexdigest()[:12]
    )


def group_similar_articles(
    items: list[dict],
    *,
    threshold: float = _DEFAULT_THRESHOLD,
) -> list[SimilarGroup]:
    """Group near-duplicate articles by title+summary cosine similarity.

    `items` are mappings with at least `id` (int); blank title+summary
    means "no signal" — the item never groups. Union-find over pairs at
    or above `threshold`; returns groups of size >= 2 only, in
    first-appearance order. Empty input or no qualifying pairs yields [].
    """
    vectors: dict[int, Counter[str]] = {}
    order: list[int] = []
    id_by_position: dict[int, int] = {}
    for position, item in enumerate(items):
        item_id = _parse_id(item)
        if item_id is None or not isinstance(item, dict):
            continue
        feats = _features(_document_text(item))
        if not feats:
            continue
        vectors[position] = feats
        order.append(position)
        id_by_position[position] = item_id

    groups: list[SimilarGroup] = []
    for members in _cluster_positions(vectors, order, threshold):
        member_ids = tuple(id_by_position[p] for p in members)
        scores = [
            _cosine(vectors[members[i]], vectors[members[j]])
            for i in range(len(members))
            for j in range(i + 1, len(members))
        ]
        groups.append(
            SimilarGroup(
                group_id=_group_fingerprint(member_ids),
                master_id=id_by_position[members[0]],
                member_ids=member_ids,
                confidence=round(min(scores), 3) if scores else 0.0,
            )
        )
    # Stable first-appearance order: sort by the position of the master.
    master_position = {mid: p for p, mid in id_by_position.items()}
    groups.sort(key=lambda g: master_position[g.master_id])
    return groups
