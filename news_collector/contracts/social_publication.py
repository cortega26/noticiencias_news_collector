"""Adapter: assign / preserve the social-distribution decision for a post.

Plan ``social-distribution`` §8 (identity + detection) and §9 (front-matter
contract). This module is a shape-conversion + deterministic-derivation choke
point (LAW-B2): it decides nothing editorial and performs no I/O — no network,
no DB sessions, no filesystem, no orchestration imports.

Responsibilities:

* ``derive_social_id`` — deterministic ``social.id`` from a stored ``source_url``.
* ``apply_social_decision`` — pure front-matter ``dict`` -> ``dict``: strip any
  LLM-produced ``social``, then preserve the previous file's decision exactly or
  derive a fresh opt-in for a brand-new file.
* ``stamp_social_frontmatter`` — apply the decision to a full Markdown document
  string, re-serialising *only* the front-matter and keeping the body byte for
  byte. Returns the input unchanged when nothing changed.

The LLM never decides authorisation: any ``social`` block in the generated
front-matter is discarded before the decision is computed.
"""

from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml

from .frontend_schema import SOCIAL_ID_PATTERN

__all__ = [
    "SOCIAL_ID_PATTERN",
    "SOCIAL_ID_RE",
    "SOCIAL_ID_HASH_PREFIX",
    "derive_social_id",
    "apply_social_decision",
    "stamp_social_frontmatter",
]

# ``\Z`` (not ``$``): Python's ``re`` lets ``$`` match before a trailing
# newline, while Pydantic's rust-regex and the frontend's ``RegExp.test`` both
# anchor at end-of-input. Without this, ``SOCIAL_ID_RE`` — which is exported for
# downstream consumers (manifest / ledger) — would accept an id the two schema
# contracts reject.
SOCIAL_ID_RE = re.compile(SOCIAL_ID_PATTERN.replace("$", r"\Z"))

# Frozen domain-separation prefix for the identity hash (plan §8). Never change
# this string: it would re-key every future article's distribution ledger entry.
SOCIAL_ID_HASH_PREFIX = "noticiencias.com/social/v1\n"

_FRONTMATTER_OPEN = "---\n"
_FRONTMATTER_CLOSE = "\n---"


def derive_social_id(source_url: str) -> str:
    """Return the lowercase SHA-256 hex digest that identifies *source_url*.

    ``sha256(b"noticiencias.com/social/v1\\n" + NFC(source_url.strip()))``.

    The caller passes the ``source_url`` string exactly as persisted in the
    front-matter (already normalised upstream by ``pydantic.HttpUrl``); redirects
    are not followed and query/fragment are not stripped.
    """
    normalized = unicodedata.normalize("NFC", source_url.strip())
    digest = hashlib.sha256(
        (SOCIAL_ID_HASH_PREFIX + normalized).encode("utf-8")
    ).hexdigest()
    return digest


def _is_usable_source_url(value: Any) -> bool:
    """True when *value* is an http(s) URL with a host — the only shape that may
    auto-authorise distribution.

    A prefix test is not enough: ``"http://"`` starts with the scheme yet has no
    host, and hashing it would stamp ``publish: true`` on garbage. The parse is
    structural only (``urlsplit``); reachability is never checked here.
    """
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or any(ch.isspace() for ch in candidate):
        return False
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    # `hostname` is None for `http://`, `http://:8080` and `http://@x`-style
    # userinfo-only authorities.
    return bool(parts.hostname)


def apply_social_decision(
    *,
    generated_frontmatter: Mapping[str, Any],
    previous_frontmatter: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve the ``social`` key for a post's front-matter.

    ``previous_frontmatter`` is ``None`` iff no previous target file exists (a
    brand-new article). A previous file's ``social`` (or its absence) is
    authoritative and preserved exactly; only a brand-new file gets a freshly
    derived opt-in. Any ``social`` in *generated_frontmatter* is dropped first.

    Returns a new dict; the inputs are not mutated.
    """
    result: dict[str, Any] = {
        key: value for key, value in generated_frontmatter.items() if key != "social"
    }

    if previous_frontmatter is not None:
        previous_social = previous_frontmatter.get("social")
        if previous_social is not None:
            # Preserve the prior decision verbatim (including publish:false).
            result["social"] = copy.deepcopy(previous_social)
        # A previous file without `social` keeps the absence — no backfill.
        return result

    # Brand-new file: explicit opt-in decision.
    source_url = generated_frontmatter.get("source_url")
    if _is_usable_source_url(source_url):
        result["social"] = {"publish": True, "id": derive_social_id(str(source_url))}
    else:
        # No usable source: leave disabled, awaiting manual editorial opt-in.
        result["social"] = {"publish": False}
    return result


def _split_frontmatter(content: str) -> tuple[str, str] | None:
    """Split ``---\\n<fm>\\n---<rest>`` using the same heuristic as
    ``refinery_engine._has_quoted_date_only_frontmatter``.

    Returns ``(frontmatter_text, rest)`` where *rest* is everything from the
    closing ``---`` marker onward (byte for byte), or ``None`` when *content*
    has no parseable front-matter fence.
    """
    if not content.startswith(_FRONTMATTER_OPEN):
        return None
    end = content.find(_FRONTMATTER_CLOSE, len(_FRONTMATTER_OPEN))
    if end == -1:
        return None
    frontmatter_text = content[len(_FRONTMATTER_OPEN) : end]
    rest = content[end + len(_FRONTMATTER_CLOSE) :]
    return frontmatter_text, rest


def _load_frontmatter_dict(frontmatter_text: str) -> dict[str, Any] | None:
    try:
        parsed = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError:
        return None
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        return None
    return parsed


def _dump_frontmatter(frontmatter: Mapping[str, Any]) -> str:
    # Identical kwargs to the editor's own dump (ai_editor._normalize... call
    # site): dropping any of these silently reformats the file.
    return yaml.safe_dump(
        dict(frontmatter),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1000,
    ).strip()


def stamp_social_frontmatter(
    generated_content: str,
    previous_content: str | None,
) -> str:
    """Return *generated_content* with the ``social`` decision applied.

    * *generated_content* without a parseable front-matter fence is returned
      unchanged (fixing invalid content is not this function's job).
    * *previous_content* that exists but has no parseable front-matter dict
      raises ``ValueError`` — a corrupt prior file must not be treated as new.
    * When the decision does not change the front-matter, the input string is
      returned unchanged (byte identical).
    * Otherwise only the front-matter block is re-serialised; the body
      (everything after the closing ``---``, including any trailing
      ``source_identity`` comment) is preserved exactly.
    """
    # The previous file is validated FIRST, before any early return on the
    # generated side. A corrupt prior file must block the write even when the
    # generated document is itself unparseable — otherwise the one case where
    # both sides are broken is exactly the case that silently clobbers a
    # stored editorial decision.
    previous_frontmatter: dict[str, Any] | None = None
    if previous_content is not None:
        previous_split = _split_frontmatter(previous_content)
        previous_frontmatter = (
            _load_frontmatter_dict(previous_split[0])
            if previous_split is not None
            else None
        )
        if previous_frontmatter is None:
            raise ValueError(
                "previous target file has no parseable YAML front-matter; "
                "refusing to overwrite it as if it were a new article"
            )

    split = _split_frontmatter(generated_content)
    if split is None:
        return generated_content
    frontmatter_text, rest = split

    generated_frontmatter = _load_frontmatter_dict(frontmatter_text)
    if generated_frontmatter is None:
        # Generated front-matter is malformed YAML: leave it for downstream
        # validation to reject rather than rewriting it here.
        return generated_content

    decided = apply_social_decision(
        generated_frontmatter=generated_frontmatter,
        previous_frontmatter=previous_frontmatter,
    )
    if decided == generated_frontmatter:
        return generated_content

    return f"{_FRONTMATTER_OPEN}{_dump_frontmatter(decided)}{_FRONTMATTER_CLOSE}{rest}"
