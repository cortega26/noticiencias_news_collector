"""Exercise the real editorial policy integrity gate (plan 136).

Every other test that touches ``EditorialPolicy.verify_integrity`` patches it
out, so a change that neuters the gate (an early return, a wrong manifest
path, comparing a value to itself, dropping the canonicalization) used to
leave the suite green. These tests drive the real method against real
``tmp_path`` manifests: no mocks of the subject, no network, no shared state.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from loguru import logger

from news_collector.editorial.policy import EditorialPolicy, IntegrityError


def _write_manifest(path: Path, policy: EditorialPolicy) -> Path:
    """Write a valid manifest for ``policy`` and return its path."""
    manifest_path = path / "policy_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"version": policy.version, "sha256": policy.compute_sha256()},
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path


@pytest.fixture
def loguru_records():
    """Capture loguru records, since caplog only observes stdlib logging."""
    records: list[tuple[str, str]] = []

    def _sink(message) -> None:
        records.append((message.record["level"].name, message.record["message"]))

    sink_id = logger.add(_sink)
    try:
        yield records
    finally:
        logger.remove(sink_id)


class TestPolicyIntegrityReal:
    """Real-file integration for the tamper-detection gate."""

    def test_matching_manifest_verifies_and_records_hash(self, tmp_path: Path):
        """A manifest built from the policy's own hash is accepted."""
        policy = EditorialPolicy.from_mode("standard")
        manifest_path = _write_manifest(tmp_path, policy)

        assert policy.policy_sha256 == ""

        policy.verify_integrity(manifest_path)

        assert policy.policy_sha256 == policy.compute_sha256()

    def test_tampered_policy_field_fails_integrity(self, tmp_path: Path):
        """Changing a hashed field after the manifest was written must fail."""
        policy = EditorialPolicy.from_mode("standard")
        manifest_path = _write_manifest(tmp_path, policy)

        policy.critic_threshold = 55.0

        with pytest.raises(IntegrityError) as excinfo:
            policy.verify_integrity(manifest_path)

        assert "integrity" in str(excinfo.value).lower()

    def test_missing_manifest_raises_integrity_error(self, tmp_path: Path):
        """A non-existent manifest must fail closed, not silently pass."""
        policy = EditorialPolicy.from_mode("standard")

        with pytest.raises(IntegrityError):
            policy.verify_integrity(tmp_path / "does-not-exist.json")

    def test_version_mismatch_warns_but_does_not_raise(
        self, tmp_path: Path, loguru_records
    ):
        """Version drift is advisory; a matching hash still verifies."""
        policy = EditorialPolicy.from_mode("standard")
        manifest_path = tmp_path / "policy_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {"version": "9.9.9", "sha256": policy.compute_sha256()},
                indent=2,
            ),
            encoding="utf-8",
        )

        policy.verify_integrity(manifest_path)

        assert policy.policy_sha256 == policy.compute_sha256()
        assert any(level == "WARNING" for level, _message in loguru_records)

    def test_malformed_manifest_json_wraps_into_integrity_error(self, tmp_path: Path):
        """Garbage on disk must surface as IntegrityError, not JSONDecodeError."""
        policy = EditorialPolicy.from_mode("standard")
        manifest_path = tmp_path / "policy_manifest.json"
        manifest_path.write_text("{ this is not json", encoding="utf-8")

        with pytest.raises(IntegrityError):
            policy.verify_integrity(manifest_path)

    def test_hash_is_deterministic_and_covers_all_policy_fields(self):
        """Same policy -> same hash; every hashed field -> different hash."""
        base = EditorialPolicy(
            mode="standard",
            critic_threshold=80.0,
            auditor_threshold=8.0,
            require_caveats=True,
            require_no_hallucinations=False,
        )
        rebuilt = EditorialPolicy(
            mode="standard",
            critic_threshold=80.0,
            auditor_threshold=8.0,
            require_caveats=True,
            require_no_hallucinations=False,
        )

        assert base.compute_sha256() == rebuilt.compute_sha256()

        variants = {
            "mode": "strict",
            "critic_threshold": 80.5,
            "auditor_threshold": 8.5,
            "require_caveats": False,
            "require_no_hallucinations": True,
        }
        for field, value in variants.items():
            changed = replace(base, **{field: value})
            assert changed.compute_sha256() != base.compute_sha256(), field
