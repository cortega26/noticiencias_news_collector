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


import bleach

import lxml.html

def clean_html(html: str) -> str:
    if not html:
        return ""
    
    try:
        # lxml.html.fromstring can parse fragments or documents
        # It handles malformed HTML reasonably well (mimicking browsers)
        try:
            doc = lxml.html.fragment_fromstring(html, create_parent='div')
        except Exception:
            # Fallback for full documents or edge cases
            doc = lxml.html.fromstring(html)
            
        # Security: Remove potentially dangerous tags AND their content
        # strip_elements would just remove tag, drop_tree removes content too
        for element in doc.xpath('//script|//style|//noscript'):
            element.drop_tree()
            
        # Remove common boilerplate patterns from the text
        text = doc.text_content()
        
        # We can still apply the boilerplate regex removal if needed, 
        # but text_content() returns a string.
        # The original logic applied regex on *nodes*. 
        # For simplicity and safety, let's just return the text now, 
        # and if strict boilerplate removal is needed, we apply it on the string.
        
        return normalize_text(text)
        
    except Exception as e:
        # Fallback to simple regex if lxml fails completely (unlikely)
        import re
        # This is a last resort "strip everything"
        text = re.sub(r'<[^>]+>', ' ', html)
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
