"""Hero image alt-text resolution (EDITORIAL_VOICE.md: screen-reader UX).

Root fix for a Codex P2 finding (PR #144): the image pipeline stamped
`Ilustración editorial relacionada con {ENGLISH original title}` because
the fallback ran before translation. Good human-written brief alts are
kept verbatim; empty or boilerplate alts are recomputed once the Spanish
title is known (frontmatter assembly).

The recomputed fallback is the Spanish headline itself. The old
`Ilustración editorial relacionada con …` template is rejected by the
frontend `check-image-alt` gate, so publishing it would fail the PR —
and a missing alt must never block publication. Title-as-alt already
exists in the published corpus. Real visual descriptions remain the job
of editorial briefs (or a future vision model), not of this function.

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


def resolve_hero_alt_text(image_alt: Any, spanish_title: Any) -> str | None:
    """Return the publishable hero alt text.

    Keeps good alts untouched; replaces empty/boilerplate ones with the
    Spanish headline so neither English nor the gate-rejected boilerplate
    reaches the frontend. When no Spanish title is available either,
    returns the current value unchanged (fail-open parity — never worse
    than today).
    """
    current = _first_text(image_alt)
    if current is not None and not is_boilerplate_alt(current):
        return current
    title = _first_text(spanish_title)
    if not title:
        return current
    return title
