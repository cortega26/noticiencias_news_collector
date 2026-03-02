import re
from pathlib import Path


def _contracts_registry_text() -> str:
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "context" / "CONTRACTS.md"
    return path.read_text(encoding="utf-8")


def test_contracts_registry_has_non_authoritative_banner():
    text = _contracts_registry_text()
    assert "NON-AUTHORITATIVE DOCUMENT" in text
    assert "derived registry for reference purposes only" in text
    assert "docs/AGENTS.md" in text


def test_contracts_registry_does_not_redefine_law_1a_wording():
    text = _contracts_registry_text()
    forbidden_phrases = (
        "LAW-1A",
        "SourceRegistry Identity & Schema Governance",
        "source_id is the canonical identity key for news sources",
    )
    for phrase in forbidden_phrases:
        assert phrase not in text


def test_contracts_registry_normative_terms_require_agents_reference():
    text = _contracts_registry_text()
    normative = re.compile(r"\b(must|shall|required)\b", flags=re.IGNORECASE)

    for line in text.splitlines():
        if normative.search(line):
            assert "AGENTS.md" in line
