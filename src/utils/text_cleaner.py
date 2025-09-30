from __future__ import annotations

import html as _html
import re
import unicodedata
from typing import Iterable
from bs4 import BeautifulSoup


_BOILERPLATE_PATTERNS: Iterable[re.Pattern] = [
    re.compile(r"^\s*read more\s*$", re.I),
    re.compile(r"^\s*continue reading\s*$", re.I),
    re.compile(r"^\s*the post .* appeared first on .*", re.I),
]


def normalize_text(text: str) -> str:
    if not text:
        return ""
    # HTML entities and unicode normalization
    text = _html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    # Strip control chars
    text = text.replace("\x00", "").replace("\r", " ").replace("\n", " ")
    # Collapse whitespace deterministically
    text = " ".join(text.split())
    return text.strip()


def clean_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    # Remove common boilerplate nodes by text
    for el in list(soup.find_all(text=True)):
        txt = normalize_text(str(el))
        if any(p.search(txt) for p in _BOILERPLATE_PATTERNS):
            try:
                el.extract()
            except Exception:
                pass
    text = soup.get_text(" ")
    return normalize_text(text)


def detect_language_simple(text: str) -> str:
    """Deterministic heuristic EN/ES detector. Returns 'en' or 'es'."""
    if not text:
        return "en"
    t = normalize_text(text).lower()
    es_sw = {
        "de",
        "la",
        "el",
        "y",
        "que",
        "en",
        "los",
        "para",
        "con",
        "las",
        "del",
        "se",
        "un",
        "una",
    }
    en_sw = {
        "the",
        "and",
        "of",
        "to",
        "in",
        "for",
        "on",
        "with",
        "as",
        "is",
        "that",
        "this",
    }
    es = sum(1 for w in es_sw if re.search(rf"\b{re.escape(w)}\b", t))
    en = sum(1 for w in en_sw if re.search(rf"\b{re.escape(w)}\b", t))
    # Prefer Spanish if accents seen and counts tie
    has_accents = bool(re.search(r"[áéíóúñ]", t))
    if es > en:
        return "es"
    if en > es:
        return "en"
    return "es" if has_accents else "en"
