
import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

url = "https://livescience.com/animals/cats/ancient-mummified-cheetahs-discovered-in-saudi-arabia-contain-preserved-dna-from-the-long-lost-population"

def test_fetch():
    print(f"Fetching {url}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(url, timeout=10, headers=headers)
        print(f"Status Code: {response.status_code}")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Check standard tags
        article = soup.find('article')
        main = soup.find('main')
        body = soup.body
        
        print(f"Found <article>: {bool(article)}")
        if article:
            print(f"Article Text Len: {len(article.get_text(strip=True))}")
            
        print(f"Found <main>: {bool(main)}")
        if main:
            print(f"Main Text Len: {len(main.get_text(strip=True))}")
            
        # Check specific classes often used
        div_content = soup.find("div", class_=lambda x: x and "content" in x)
        print(f"Found div with 'content' class: {bool(div_content)}")
        
        # Check for blocking messages
        text = soup.get_text()
        if "enable JavaScript" in text or "Access Denied" in text:
             print("BLOCKING DETECTED in text!")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_fetch()
