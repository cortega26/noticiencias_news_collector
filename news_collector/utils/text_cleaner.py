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
            doc = lxml.html.fromstring(html)
            
        # Security: Remove potentially dangerous tags AND their content
        for element in doc.xpath('//script|//style|//noscript'):
            element.drop_tree()
            
        # Extract text with spacing to avoid "0read more" concatenation issues
        # itertext() yields text chunks; joining with space ensures separation
        chunks = []
        for hunk in doc.itertext():
            if hunk:
                chunks.append(hunk)
        text = " ".join(chunks)

        # Apply boilerplate patterns on the text (case-insensitive)
        # We need to process line by line or check standard phrases
        # normalize_text will collapse spaces, so we check cleaned version potentially?
        # But boilerplate patterns expect "read more" etc.
        
        # Simple line-based filtering (since patterns assume standalone lines usually)
        # But HTML often doesn't have newlines.
        # Let's check if the *entire* text (or end of it) matches a pattern if it's short?
        # Or simple find/replace for known phrases if they appear detached?
        
        # The original patterns were: ^\s*read more\s*$, etc.
        # This implies checking "lines".
        # Let's normalize first to get clean text, then check keys.
        
        text = normalize_text(text)
        
        # Check against patterns - if the WHOLE text is JUST boilerplate, clear it?
        # Or if it ends with it?
        # The test expects "Read More" to be removed from "<p>Read More</p>".
        # If the input was just boilerplate, it returns empty?
        
        for pattern in _BOILERPLATE_PATTERNS:
            # If the text *contains* the pattern as a distinct sentence or standalone?
            # The regexes have ^ and $, so they match the WHOLE string.
            # If the extracted text is JUST "Read More", wipe it.
            if pattern.search(text):
                return ""
                
            # What if it is "Content. Read More"?
            # The patterns are anchored ^$.
            # So they only remove if the text is ONLY boilerplate (e.g. from a button).
            # The test case passes "0 Read More" (after fix).
            # "0 Read More" does not match ^read more$.
            # Wait, the test payload is: <div>0</div><p>Read More</p>.
            # If we flatten it to "0 Read More", we lose the structure that "Read More" was a separate block.
            # This suggests we should filter *nodes* or *lines* before flattening.
            pass
            
        # Refined strategy: Filter "bad" chunks before joining
        cleaned_chunks = []
        for hunk in chunks:
            # Clean component
            norm = normalize_text(hunk)
            if not norm: 
                continue
                
            is_bad = False
            for pattern in _BOILERPLATE_PATTERNS:
                if pattern.search(norm):
                    is_bad = True
                    break
            
            if not is_bad:
                cleaned_chunks.append(hunk)
                
        text = " ".join(cleaned_chunks)
        
        return normalize_text(text)
        
    except Exception as e:
        # Fallback
        import re
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
