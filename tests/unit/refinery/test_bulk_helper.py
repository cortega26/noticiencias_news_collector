"""
Plan 017 — Bulk article action helper unit tests.

Tests the ``run_bulk`` helper's continue-on-error semantics, batch cap,
and structured reporting. The helper is pure (no Streamlit/git/DB I/O);
the per-item action is injected by the caller.

Run: .venv/bin/python -m pytest tests/unit/refinery/test_bulk_helper.py -q
"""

from __future__ import annotations

import pytest

from apps.refinery.bulk_helper import BulkFailure, BulkResult, run_bulk


class TestRunBulk:
    """Tests for the run_bulk helper."""

    def test_all_succeed(self):
        """A batch where every item succeeds."""
        results: list[int] = []

        def action(item: int) -> None:
            results.append(item)

        result = run_bulk(items=[1, 2, 3], action=action, batch_cap=5)

        assert result.all_succeeded is True
        assert len(result.succeeded) == 3
        assert len(result.failed) == 0
        assert results == [1, 2, 3]
        assert result.summary == "3 succeeded, 0 failed"

    def test_partial_failure_continues(self):
        """If item 3 fails, items 1-2 succeed and item 4 is still processed."""
        results: list[int] = []

        def action(item: int) -> None:
            if item == 3:
                raise RuntimeError("boom on item 3")
            results.append(item)

        result = run_bulk(items=[1, 2, 3, 4], action=action, batch_cap=5)

        assert result.all_succeeded is False
        assert len(result.succeeded) == 3
        assert len(result.failed) == 1
        assert result.failed[0].item == 3
        assert "boom on item 3" in result.failed[0].error
        # Items 1, 2, 4 were all processed
        assert results == [1, 2, 4]
        assert result.summary == "3 succeeded, 1 failed"

    def test_first_item_fails(self):
        """If the first item fails, the rest still process."""

        def action(item: str) -> None:
            if item == "a":
                raise ValueError("first item failed")

        result = run_bulk(items=["a", "b", "c"], action=action, batch_cap=5)

        assert len(result.succeeded) == 2
        assert len(result.failed) == 1
        assert result.failed[0].item == "a"

    def test_last_item_fails(self):
        """If the last item fails, the preceding items still succeed."""

        def action(item: int) -> None:
            if item == 3:
                raise OSError("disk full")

        result = run_bulk(items=[1, 2, 3], action=action, batch_cap=5)

        assert len(result.succeeded) == 2
        assert len(result.failed) == 1
        assert result.failed[0].item == 3
        assert "disk full" in result.failed[0].error

    def test_batch_cap_truncates(self):
        """Items beyond the batch cap are not processed."""
        results: list[int] = []

        def action(item: int) -> None:
            results.append(item)

        result = run_bulk(items=[1, 2, 3, 4, 5, 6, 7, 8], action=action, batch_cap=3)

        assert len(result.succeeded) == 3
        assert results == [1, 2, 3]
        # The cap-exceeded note is recorded as a failure
        assert len(result.failed) == 1
        assert result.failed[0].item is None
        assert "exceeds cap" in result.failed[0].error

    def test_empty_items(self):
        """An empty items list produces an empty result."""
        result = run_bulk(items=[], action=lambda x: None, batch_cap=5)

        assert result.all_succeeded is True
        assert len(result.succeeded) == 0
        assert len(result.failed) == 0
        assert result.summary == "0 succeeded, 0 failed"

    def test_multiple_failures(self):
        """Multiple failures are all captured, not just the first."""
        errors = {2: "err2", 4: "err4"}

        def action(item: int) -> None:
            if item in errors:
                raise RuntimeError(errors[item])

        result = run_bulk(items=[1, 2, 3, 4, 5], action=action, batch_cap=10)

        assert len(result.succeeded) == 3
        assert len(result.failed) == 2
        failed_items = {f.item for f in result.failed}
        assert failed_items == {2, 4}

    def test_action_return_value_ignored(self):
        """The action's return value is not stored in succeeded; only the item is."""

        def action(item: str) -> str:
            return f"processed-{item}"

        result = run_bulk(items=["a", "b"], action=action, batch_cap=5)

        assert result.succeeded == ["a", "b"]

    def test_total_property(self):
        """The total property counts succeeded + failed."""

        def action(item: int) -> None:
            if item % 2 == 0:
                raise RuntimeError("even failed")

        result = run_bulk(items=[1, 2, 3, 4, 5], action=action, batch_cap=10)

        assert result.total == 5

    def test_divergence_bug_does_not_occur(self):
        """
        Regression test for the divergence bug from the rejected UI slice.

        The old batched approach deleted DB rows before the filesystem
        operation, so a failure at unlink left the DB/file/git diverged.
        The run_bulk helper never touches DB rows — the caller's action
        is responsible for the full lifecycle. This test verifies that
        if the action fails, the item is simply recorded as failed; no
        partial state is visible to the helper.
        """
        state: dict[str, bool] = {"db_deleted": False, "file_deleted": False}

        def buggy_action(item: str) -> None:
            # Simulate the old buggy sequence: delete DB first, then file
            state["db_deleted"] = True
            # File deletion fails
            raise OSError("permission denied")
            state["file_deleted"] = True  # never reached

        result = run_bulk(items=["article.md"], action=buggy_action, batch_cap=5)

        # The helper records the failure
        assert len(result.failed) == 1
        assert "permission denied" in result.failed[0].error
        # The helper itself did not touch any state — the caller's action
        # is responsible for its own rollback. The helper's contract is:
        # "if the action raises, the item is failed; the loop continues."
        assert state["db_deleted"] is True  # the action's side effect
        assert state["file_deleted"] is False  # the action's failure

    def test_batch_cap_zero_means_no_cap(self):
        """A batch_cap of 0 means no cap — all items are processed."""
        results: list[int] = []

        def action(item: int) -> None:
            results.append(item)

        result = run_bulk(
            items=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], action=action, batch_cap=0
        )

        assert len(result.succeeded) == 10
        assert len(result.failed) == 0
        assert result.all_succeeded is True

    def test_batch_cap_negative_means_no_cap(self):
        """A negative batch_cap means no cap — all items are processed."""
        results: list[int] = []

        def action(item: int) -> None:
            results.append(item)

        result = run_bulk(items=[1, 2, 3], action=action, batch_cap=-1)

        assert len(result.succeeded) == 3
        assert len(result.failed) == 0

    def test_cap_exceeded_note_is_warning_not_failure(self):
        """The cap-exceeded note (item=None) should not make all_succeeded False."""
        result = run_bulk(
            items=[1, 2, 3, 4, 5, 6, 7, 8],
            action=lambda x: None,
            batch_cap=3,
        )

        # 3 items succeeded, 1 cap-exceeded note (item=None)
        assert len(result.succeeded) == 3
        assert len(result.failed) == 1
        assert result.failed[0].item is None
        # all_succeeded is True because no real items failed
        assert result.all_succeeded is True
        # total counts only real items (3 processed), not the note
        assert result.total == 3

    def test_cap_exceeded_with_real_failure(self):
        """Cap-exceeded note + a real failure: all_succeeded is False."""

        def action(item: int) -> None:
            if item == 2:
                raise RuntimeError("fail on 2")

        result = run_bulk(items=[1, 2, 3, 4, 5, 6, 7, 8], action=action, batch_cap=3)

        assert len(result.succeeded) == 2  # 1 and 3
        assert len(result.failed) == 2  # item 2 (real failure) + cap note
        assert result.all_succeeded is False
        assert result.total == 3  # 2 succeeded + 1 real failure
