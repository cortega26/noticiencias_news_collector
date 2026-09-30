"""Hero image alt-text resolution (EDITORIAL_VOICE.md: screen-reader UX).

Root fix for a Codex P2 finding (PR #144): the image pipeline stamped
`Ilustración editorial relacionada con {ENGLISH original title}` because
the fallback ran before translation. Good human-written brief alts are
kept verbatim; empty or boilerplate alts are recomputed once the Spanish
title is known (frontmatter assembly).

The recomputed fallback is the Spanish headline itself. The old
`Ilustración editorial relacionada con …` template is rejected by the
frontend `check-image-alt` gate, so publishing it would fail the PR —
and a missing alt must never block publication. A headline that itself
starts with a rejected prefix is stripped of it, so this module never
returns a gate-rejected value. Title-as-alt already exists in the
published corpus. Real visual descriptions remain the job of editorial
briefs (or a future vision model), not of this function.

Pure stdlib: no network, no DB, no LLM. Never raises.
"""

from __future__ import annotations

from typing import Any

# Boilerplate markers (case-insensitive prefixes): this pipeline's former
# fallback template and the prohibited generic prefix
# `publication_safe_image_alt` already treats as missing. Kept to detect
# legacy exports and to refuse boilerplate brief alts.
BOILERPLATE_ALT_PREFIXES = (
    "ilustración editorial relacionada con",
    "imagen de",
)

# Last-resort alt when a boilerplate-shaped value leaves nothing usable
# after prefix stripping. Generic but gate-safe (no rejected prefix).
_GENERIC_ALT_FALLBACK = "Ilustración del artículo"


def is_boilerplate_alt(text: Any) -> bool:
    """Whether an alt text is a boilerplate placeholder rather than a
    description (or empty/missing)."""
    if not isinstance(text, str):
        return True
    stripped = text.strip()
    if not stripped:
        return True
    lowered = stripped.casefold()
    return lowered.startswith(BOILERPLATE_ALT_PREFIXES)


def _first_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (list, tuple)) and value:
        return _first_text(value[0])
    return None


def _escape_boilerplate(text: str) -> str:
    """Strip a leading rejected prefix from `text`.

    A Spanish headline can itself start with `Imagen de …` or the old
    `Ilustración editorial relacionada con …` template; returning it
    verbatim would still fail the frontend `check-image-alt` gate. When
    stripping leaves nothing usable, return a generic gate-safe phrase.
    """
    lowered = text.casefold()
    for prefix in BOILERPLATE_ALT_PREFIXES:
        if lowered.startswith(prefix):
            remainder = text[len(prefix) :].lstrip(" :;,-–—»").strip()
            if remainder:
                return remainder[0].upper() + remainder[1:]
    return _GENERIC_ALT_FALLBACK


def resolve_hero_alt_text(image_alt: Any, spanish_title: Any) -> str | None:
    """Return the publishable hero alt text.

    Keeps good alts untouched; replaces empty/boilerplate ones with the
    Spanish headline so neither English nor the gate-rejected boilerplate
    reaches the frontend. A boilerplate-shaped headline (or current value
    when no headline exists) is stripped of the rejected prefix. Never
    returns a string the frontend gate would reject.
    """
    current = _first_text(image_alt)
    if current is not None and not is_boilerplate_alt(current):
        return current
    title = _first_text(spanish_title)
    if not title:
        return current if current is None else _escape_boilerplate(current)
    if is_boilerplate_alt(title):
        return _escape_boilerplate(title)
    return title
