import httpx
from bs4 import BeautifulSoup


def inspect_page():
    url = "https://blog.google/products/gemini/gemini-3/"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=10)
        print(f"Status: {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")

        # Check standard containers
        article = soup.find("article")
        soup.find("main")
        soup.find("div", class_="content")

        print(f"Has <article>: {headers}")  # Typo in print, but reusing var
        print(f"Has <article>: {bool(article)}")
        if article:
            print(f"Article classes: {article.get('class')}")
            ps = article.find_all("p")
            print(f"Paragraphs found: {len(ps)}")
            for i, p in enumerate(ps[:5]):
                print(f"P[{i}]: {p.get_text(strip=True)[:50]}...")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    inspect_page()
