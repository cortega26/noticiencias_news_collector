"""
Plan 049 — Versioned publication feed contract prototype (SPIKE).

Synthetic, non-production prototype testing the feed revision contract.
Does NOT touch network, production storage, or real content.

Run: .venv/bin/python -m pytest tests/spikes/test_publication_feed.py -q
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pytest


class FeedOperation(str, Enum):
    UPSERT = "upsert"
    TOMBSTONE = "tombstone"


@dataclass
class FeedRevision:
    """Versioned feed revision (synthetic prototype)."""

    feed_version: int = 1
    revision: int = 0
    parent: int | None = None
    producer_commit: str = "abc123"
    generated_at: str = ""
    operation: FeedOperation = FeedOperation.UPSERT
    refinery_id: str = ""
    canonical_slug: str = ""
    content_hash: str = ""
    frontmatter: str = ""
    body: str = ""
    assets: list[dict[str, str]] = field(default_factory=list)
    prior_revision: int | None = None
    batch_hash: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()
        if not self.content_hash:
            self.content_hash = hashlib.sha256(
                (self.frontmatter + self.body).encode()
            ).hexdigest()

    def canonical_json(self) -> str:
        """Canonical serialization with sorted keys."""
        d = {
            "feed_version": self.feed_version,
            "revision": self.revision,
            "parent": self.parent,
            "producer_commit": self.producer_commit,
            "generated_at": self.generated_at,
            "operation": self.operation.value,
            "refinery_id": self.refinery_id,
            "canonical_slug": self.canonical_slug,
            "content_hash": self.content_hash,
            "prior_revision": self.prior_revision,
            "batch_hash": self.batch_hash,
        }
        return json.dumps(d, sort_keys=True, separators=(",", ":"))


class FeedStore:
    """In-memory feed store (synthetic prototype)."""

    def __init__(self):
        self._revisions: list[FeedRevision] = []
        self._by_id: dict[str, list[int]] = {}  # refinery_id -> revision indices

    def append(self, rev: FeedRevision) -> None:
        # Validate version
        if rev.feed_version != 1:
            raise ValueError(f"Unknown feed version: {rev.feed_version}")

        # Validate revision is monotonic
        if self._revisions and rev.revision <= self._revisions[-1].revision:
            raise ValueError(
                f"Non-monotonic revision: {rev.revision} <= {self._revisions[-1].revision}"
            )

        # Validate parent
        if rev.parent is not None:
            if rev.parent != rev.revision - 1:
                raise ValueError(
                    f"Parent must be revision-1: parent={rev.parent}, revision={rev.revision}"
                )

        # Check for duplicate (same refinery_id + content_hash)
        for idx in self._by_id.get(rev.refinery_id, []):
            existing = self._revisions[idx]
            if (
                existing.content_hash == rev.content_hash
                and existing.operation == rev.operation
            ):
                raise ValueError(
                    f"Duplicate revision: {rev.refinery_id} + {rev.content_hash[:8]}"
                )

        # Tombstone requires prior upsert
        if rev.operation == FeedOperation.TOMBSTONE:
            if rev.refinery_id not in self._by_id:
                raise ValueError(f"Tombstone without prior upsert: {rev.refinery_id}")

        # Path traversal check
        if ".." in rev.canonical_slug or "/" in rev.refinery_id:
            raise ValueError(f"Path traversal in slug/id: {rev.refinery_id}")

        idx = len(self._revisions)
        self._revisions.append(rev)
        self._by_id.setdefault(rev.refinery_id, []).append(idx)

    def current_state(self, refinery_id: str) -> FeedRevision | None:
        indices = self._by_id.get(refinery_id, [])
        if not indices:
            return None
        return self._revisions[indices[-1]]

    def replay(self) -> list[FeedRevision]:
        """Deterministic replay of all revisions."""
        return list(self._revisions)

    def rollback_to(self, revision: int) -> list[FeedRevision]:
        """Return the state as of a prior revision (immutable, doesn't rewrite history)."""
        return [r for r in self._revisions if r.revision <= revision]


def make_revision(
    refinery_id: str = "2026-01-15-test-article",
    slug: str = "test-article",
    body: str = "# Test Article\n\nContent here.",
    revision: int = 1,
    parent: int | None = None,
    operation: FeedOperation = FeedOperation.UPSERT,
) -> FeedRevision:
    return FeedRevision(
        revision=revision,
        parent=parent,
        operation=operation,
        refinery_id=refinery_id,
        canonical_slug=slug,
        frontmatter="---\ntitle: Test\n---",
        body=body,
    )


# ─── Tests ────────────────────────────────────────────────────────────────


class TestContract:
    def test_valid_upsert(self):
        store = FeedStore()
        rev = make_revision()
        store.append(rev)
        assert len(store.replay()) == 1

    def test_unknown_version_rejected(self):
        store = FeedStore()
        rev = make_revision()
        rev.feed_version = 2
        with pytest.raises(ValueError, match="Unknown feed version"):
            store.append(rev)

    def test_non_monotonic_revision_rejected(self):
        store = FeedStore()
        store.append(make_revision(revision=1))
        with pytest.raises(ValueError, match="Non-monotonic"):
            store.append(make_revision(revision=1))

    def test_duplicate_rejected(self):
        store = FeedStore()
        rev = make_revision(revision=1)
        store.append(rev)
        dup = make_revision(revision=2, parent=1)
        dup.refinery_id = rev.refinery_id
        dup.content_hash = rev.content_hash
        with pytest.raises(ValueError, match="Duplicate"):
            store.append(dup)

    def test_tombstone_without_prior_rejected(self):
        store = FeedStore()
        rev = make_revision(revision=1, operation=FeedOperation.TOMBSTONE)
        with pytest.raises(ValueError, match="Tombstone without prior"):
            store.append(rev)

    def test_path_traversal_rejected(self):
        store = FeedStore()
        rev = make_revision()
        rev.refinery_id = "../../etc/passwd"
        with pytest.raises(ValueError, match="Path traversal"):
            store.append(rev)


class TestDeterminism:
    def test_canonical_json_is_sorted(self):
        rev = make_revision()
        cj = rev.canonical_json()
        # Parse the JSON and verify keys are sorted
        d = json.loads(cj)
        keys = list(d.keys())
        assert keys == sorted(keys), f"Keys not sorted: {keys}"

    def test_same_revision_same_json(self):
        r1 = make_revision()
        r2 = make_revision()
        r2.generated_at = r1.generated_at  # Fix timestamp for comparison
        assert r1.canonical_json() == r2.canonical_json()

    def test_replay_is_deterministic(self):
        store = FeedStore()
        for i in range(1, 11):
            rev = make_revision(
                revision=i, parent=i - 1 if i > 1 else None, body=f"# Article v{i}"
            )
            rev.generated_at = f"2026-01-01T00:00:0{i}Z"  # deterministic timestamp
            store.append(rev)
        replay1 = store.replay()
        replay2 = store.replay()
        assert [r.canonical_json() for r in replay1] == [
            r.canonical_json() for r in replay2
        ]


class TestReplayAndRollback:
    def test_rollback_returns_prior_state(self):
        store = FeedStore()
        store.append(make_revision(revision=1, body="v1"))
        store.append(make_revision(revision=2, parent=1, body="v2"))
        store.append(make_revision(revision=3, parent=2, body="v3"))
        state = store.rollback_to(1)
        assert len(state) == 1
        assert state[0].body == "v1"

    def test_tombstone_marks_current_state(self):
        store = FeedStore()
        store.append(make_revision(revision=1, refinery_id="art-1"))
        store.append(
            make_revision(
                revision=2,
                parent=1,
                refinery_id="art-1",
                operation=FeedOperation.TOMBSTONE,
            )
        )
        current = store.current_state("art-1")
        assert current is not None
        assert current.operation == FeedOperation.TOMBSTONE

    def test_correction_with_prior_revision(self):
        store = FeedStore()
        store.append(make_revision(revision=1, refinery_id="art-1", body="original"))
        correction = make_revision(
            revision=2, parent=1, refinery_id="art-1", body="corrected"
        )
        correction.prior_revision = 1
        store.append(correction)
        current = store.current_state("art-1")
        assert current.body == "corrected"
        assert current.prior_revision == 1

    def test_rollback_to_zero_returns_empty(self):
        store = FeedStore()
        store.append(make_revision(revision=1, body="v1"))
        state = store.rollback_to(0)
        assert len(state) == 0

    def test_current_state_for_nonexistent_returns_none(self):
        store = FeedStore()
        store.append(make_revision(revision=1, refinery_id="art-1"))
        assert store.current_state("nonexistent") is None

    def test_double_tombstone_rejected_as_duplicate(self):
        store = FeedStore()
        store.append(make_revision(revision=1, refinery_id="art-1", body="original"))
        store.append(
            make_revision(
                revision=2,
                parent=1,
                refinery_id="art-1",
                operation=FeedOperation.TOMBSTONE,
            )
        )
        # Second tombstone with same content_hash (empty body) is a duplicate
        with pytest.raises(ValueError, match="Duplicate"):
            store.append(
                make_revision(
                    revision=3,
                    parent=2,
                    refinery_id="art-1",
                    operation=FeedOperation.TOMBSTONE,
                )
            )

    def test_content_hash_changes_when_body_changes(self):
        r1 = make_revision(body="content A")
        r2 = make_revision(body="content B")
        assert r1.content_hash != r2.content_hash

    def test_empty_store_replay(self):
        store = FeedStore()
        assert store.replay() == []
        assert store.current_state("anything") is None
