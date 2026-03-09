import requests
from unittest.mock import MagicMock

def validate_url_safety(url):
    print(f"Validating {url}")

class SSRFSafeSession(requests.Session):
    def get_adapter(self, url):
        validate_url_safety(url)
        return super().get_adapter(url)

s = SSRFSafeSession()
try:
    s.get("http://httpbin.org/redirect-to?url=http%3A%2F%2Fexample.com")
except Exception as e:
    print(e)
