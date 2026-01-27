
import requests

urls = [
    "https://www.science.org/rss/news",
    "https://www.science.org/rss/express",
    "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
    "https://www.science.org/blogs/pipeline/feed",
    "https://www.science.org/topic/news/feed"
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

for url in urls:
    try:
        print(f"Testing {url}...")
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
             print("SUCCESS!")
             print(f"Content Start: {resp.text[:100]}")
             break
    except Exception as e:
        print(f"Error: {e}")
