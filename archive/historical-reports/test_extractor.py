import requests

from news_collector.logic.parsers.image_extractor import ImageExtractor

url = "https://scitechdaily.com/a-massive-star-suddenly-vanished-and-left-a-black-hole-behind/"
html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
extractor = ImageExtractor()
cands = extractor.extract_candidates(html, url)
for c in cands:
    print(c)
