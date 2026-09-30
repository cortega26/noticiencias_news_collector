"""Deterministic self-repair strategies for classified frontend validation
failures (self-healing publication).

The frontend publication gate (`run_frontend_publication_validation`)
classifies its failures; some of them are *mechanically* repairable — the
content is valid in every other respect, only a contract detail is wrong
(e.g. a tag containing a character the cross-repo contract forbids). This
module owns those repairs as pure functions: content in, repaired content
out. The workflow owns the I/O (reading/writing the post) and the bounded
re-run of validation.

Rules:
- A strategy may only return a repair when the contract invariant it targets
  passes afterwards (e.g. `TagNormalizer.validate_tags` is green).
- `None` means "no deterministic repair applies or nothing changed" — the
  caller must fail exactly as before, never guess.
- Pure stdlib + taxonomy policy: no network, no DB, no LLM, never raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import yaml

from news_collector.taxonomy.normalizer import TagNormalizer
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("PublicationRepairs")

_FRONTMATTER_OPEN = "---\n"
_FRONTMATTER_CLOSE = "\n---"


@dataclass(frozen=True)
class ContentRepair:
    """A repaired post plus what changed, for stage/observability details."""

    content: str
    fields: tuple[str, ...]
    descriptions: tuple[str, ...]


def _split_frontmatter(content: str) -> Optional[tuple[str, str]]:
    """Split `---` frontmatter: (block, remainder-after-closing-fence).

    Returns `None` when the file has no well-formed frontmatter; the caller
    must treat that as "not repairable" (the normal validation failure
    stands).
    """
    if not content.startswith(_FRONTMATTER_OPEN):
        return None
    end = content.find(_FRONTMATTER_CLOSE, len(_FRONTMATTER_OPEN))
    if end == -1:
        return None
    return (
        content[len(_FRONTMATTER_OPEN) : end],
        content[end + len(_FRONTMATTER_CLOSE) :],
    )


def _parse_frontmatter_mapping(frontmatter: str) -> Optional[dict]:
    """Parse a frontmatter block into a mapping, or `None` when unusable."""
    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _string_tags(data: dict) -> Optional[list[str]]:
    """The post's tag list when it is a non-empty list of strings."""
    raw_tags = data.get("tags")
    if not isinstance(raw_tags, list) or not raw_tags:
        return None
    if not all(isinstance(tag, str) for tag in raw_tags):
        return None
    return raw_tags


def _dump_frontmatter(data: dict) -> Optional[str]:
    try:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip("\n")
    except yaml.YAMLError:
        return None


def _repair_taxonomy_tags(content: str) -> Optional[ContentRepair]:
    """Repair post tags to the cross-repo charset contract.

    `ads/cft` -> `ads cft` (run 59). The repaired list is only accepted when
    `TagNormalizer.validate_tags` says the contract holds; the body is
    preserved byte-for-byte.
    """
    split = _split_frontmatter(content)
    if split is None:
        return None
    frontmatter, remainder = split
    data = _parse_frontmatter_mapping(frontmatter)
    if data is None:
        return None
    raw_tags = _string_tags(data)
    if raw_tags is None:
        return None

    normalizer = TagNormalizer()
    repaired_tags = normalizer.sanitize_tags(raw_tags).tags
    if repaired_tags == raw_tags:
        return None
    if not normalizer.validate_tags(repaired_tags).is_valid:
        # A repair that still violates the contract is not a repair.
        return None

    data["tags"] = repaired_tags
    repaired_frontmatter = _dump_frontmatter(data)
    if repaired_frontmatter is None:
        return None

    return ContentRepair(
        content=f"{_FRONTMATTER_OPEN}{repaired_frontmatter}{_FRONTMATTER_CLOSE}{remainder}",
        fields=("tags",),
        descriptions=(f"tags repaired: {raw_tags} -> {repaired_tags}",),
    )


_REPAIRERS: dict[str, Callable[[str], Optional[ContentRepair]]] = {
    "taxonomy_contract_violation": _repair_taxonomy_tags,
}


def repairable_failure_classes() -> tuple[str, ...]:
    """Failure classes with a deterministic repair strategy, sorted."""
    return tuple(sorted(_REPAIRERS))


def repair_post_content(content: str, failure_class: str) -> Optional[ContentRepair]:
    """Apply the deterministic repair for `failure_class`, if one exists.

    Returns `None` when the class has no strategy, nothing changed, the
    content is malformed, or the repaired output would still violate its
    contract. Never raises: a broken repair attempt must not kill a run that
    would otherwise fail with its original, actionable validation error.
    """
    if not isinstance(content, str) or not content:
        return None
    handler = _REPAIRERS.get(failure_class)
    if handler is None:
        return None
    try:
        return handler(content)
    except Exception as exc:  # defensive: repair must never mask the real failure
        logger.warning(
            "Publication repair strategy for {} failed; keeping the original "
            "validation failure: {}",
            failure_class,
            exc,
        )
        return None
