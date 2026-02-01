import requests

url = "https://www.science.org/rss/news"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

try:
    print(f"Fetching {url}...")
    resp = requests.get(url, headers=headers, timeout=10)
    print(f"Status: {resp.status_code}")
    print(f"Headers: {resp.headers}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    print(f"Start of content: {resp.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
