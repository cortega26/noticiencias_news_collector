import re
from typing import Any, Dict, Optional

import requests


class ScholarlyMetadataEnricher:
    """
    Fetches open bibliographic metadata (Crossref, PubMed) for academic articles
    to generate a 'publishable' summary when full-text is paywalled.
    """

    # DOI Regex (simplified, covers most standard prefixes 10.xxxx/yyyy)
    DOI_PATTERN = re.compile(r"(10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+)")

    CROSSREF_API_URL = "https://api.crossref.org/works/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "NoticienciasNewsCollector/1.0 (mailto:scholar@noticiencias.com) - Scholarly Enrichment Bot"
            }
        )

    def extract_doi(self, url: str) -> Optional[str]:
        """
        Extracts DOI from the URL string.

        Args:
            url (str): The article URL (e.g. from the feed)

        Returns:
            str | None: The extracted DOI or None if not found.
        """
        match = self.DOI_PATTERN.search(url)
        if match:
            # Clean trailing punctuation often caught by loose regex
            doi = match.group(1)
            if doi.endswith("."):
                doi = doi[:-1]
            return doi
        return None

    def fetch_metadata(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        Queries Crossref API for metadata.

        Args:
            doi (str): The DOI to lookup.

        Returns:
            dict | None: The raw metadata or None if request fails.
        """
        try:
            # "mailto" in UA is polite for Crossref for faster rate limits
            resp = self.session.get(f"{self.CROSSREF_API_URL}{doi}")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("message", {})
            return None
        except Exception:
            return None

    def format_content(
        self, metadata: Dict[str, Any], original_url: str
    ) -> Optional[str]:
        """
        Formats metadata into a structured article text.

        Structure:

        # [Title]

        **Authors**: [Author list]
        **Journal**: [Container title] ([Year])
        **DOI**: [DOI link]

        ## Abstract
        [Abstract text]

        ## Editorial Summary
        This is a scholarly summary derived from open metadata...

        Args:
            metadata: Crossref metadata dict.
            original_url: The RSS item link.

        Returns:
            str | None: The formatted content string (>= 500 chars usually) or None if abstract missing.
        """
        title = metadata.get("title", ["[Unknown Title]"])[0]

        # Authors
        authors = metadata.get("author", [])
        author_names = []
        for a in authors[:5]:  # limit to 5
            name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if name:
                author_names.append(name)
        if len(authors) > 5:
            author_names.append("et al.")
        ", ".join(author_names) if author_names else "Unknown Authors"

        # Journal & Date
        container = metadata.get("container-title", ["Unknown Journal"])
        journal_name = container[0] if container else "Unknown Journal"

        created = metadata.get("created", {}).get("date-parts", [[None]])[0]
        year = created[0] if created and created[0] else "N/A"

        doi = metadata.get("DOI", "")
        doi_link = f"https://doi.org/{doi}" if doi else "N/A"

        # Abstract (Crossref 'abstract' field is often XML-ish)
        abstract_raw = metadata.get("abstract", "")
        # Very basic cleanup of JATS XML tags often found in Crossref abstracts
        abstract_clean = re.sub(r"<[^>]+>", "", abstract_raw).strip()

        if not abstract_clean:
            # Without an abstract, we likely can't reach 500 chars of USEFUL content.
            # We fail gracefully.
            return None

        # Compose content
        content = f"""# {title}

**Authors**: {author_names}
**Journal**: {journal_name} ({year})
**DOI**: {doi_link}
**Source**: [Original Article]({original_url})

## Abstract
{abstract_clean}

## Scholarly Context
(_This summary was automatically generated from open bibliographic metadata to ensure accuracy for this paywalled article._)

The study "{title}" was published in {journal_name}. It contributes to the field by presenting the research findings summarized in the abstract above.
"""
        return content

    def enrich_url(self, url: str) -> Dict[str, Any]:
        """
        Main entry point.

        Returns:
            dict: {
                "success": bool,
                "content": str (if success),
                "metadata": dict (if success),
                "reason": str (if fail)
            }
        """
        doi = self.extract_doi(url)
        if not doi:
            return {"success": False, "reason": "no_doi_found"}

        metadata = self.fetch_metadata(doi)
        if not metadata:
            return {"success": False, "reason": "metadata_fetch_failed"}

        content = self.format_content(metadata, url)
        if not content:
            return {"success": False, "reason": "no_abstract_available"}

        if len(content) < 500:
            return {
                "success": False,
                "reason": "content_too_short_after_enrichment",
                "len": len(content),
            }

        return {
            "success": True,
            "content": content,
            "metadata": metadata,  # Can be used for extra fields
            "title": metadata.get("title", [""])[0],
        }
