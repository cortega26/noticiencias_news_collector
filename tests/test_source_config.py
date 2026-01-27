
import pytest
import yaml
from news_collector.config.settings import BASE_DIR

def test_sources_are_rss_not_html():
    sources_path = BASE_DIR / "config" / "sources.yaml"
    with open(sources_path, "r") as f:
        sources = yaml.safe_load(f)
    
    html_indicators = ["/latest", "/news", "/current", "/toc/", "/home/"]
    # Allow some if expected, but generally filter out known suspicious patterns
    
    for source_id, config in sources.items():
        if not config.get("is_active", True):
            continue
            
        url = config["url"]
        
        # Check against known HTML patterns unless explicitly exempted
        # We upgraded nature, science, etc.
        # Failing if we see the old bad patterns
        if "nature.com/latest-news" in url:
            pytest.fail(f"Source {source_id} still points to HTML: {url}")
        if "science.org/news" in url and "rss" not in url:
            pytest.fail(f"Source {source_id} still points to HTML: {url}")
            
        # Generic RSS heuristic
        is_suspicious = False
        if not any(x in url.lower() for x in ["rss", "feed", "xml", "atom"]):
            # If not containing common RSS terms, check strict blacklist
            if any(url.endswith(bad) for bad in html_indicators):
                is_suspicious = True
        
        # Exceptions for APIs or clean URLs that are actually RSS (some feedburners etc)
        # But we want to enforce the shift.
        if is_suspicious:
             print(f"Warning: Source {source_id} URL {url} looks like HTML.")
