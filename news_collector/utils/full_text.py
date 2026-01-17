
import requests
from bs4 import BeautifulSoup
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def fetch_full_article(url: str, session: Optional[requests.Session] = None) -> str:
    """
    Fetches and extracts the main text content from a URL.
    Used when RSS summary is too short.
    """
    # Use a Browser-like User-Agent to avoid being blocked (e.g. by LiveScience)
    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        if session:
            # Override session headers for this request
            response = session.get(url, timeout=15, headers=browser_headers)
        else:
            response = requests.get(url, timeout=15, headers=browser_headers)
        
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove unwanted elements
        for script in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            script.decompose()

        # Try to find the main article container
        article = soup.find('article')
        if article:
            text = article.get_text(separator=' ', strip=True)
        else:
            # Fallback to main content or body
            main = soup.find('main')
            if main:
                text = main.get_text(separator=' ', strip=True)
            else:
                text = soup.body.get_text(separator=' ', strip=True) if soup.body else ""

        # Basic cleanup
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        return text

    except Exception as e:
        logger.warning(f"Failed to fetch full text for {url}: {e}")
        return ""
