import httpx
import asyncio

def validate_url_safety(url):
    print(f"Validating {url}")

async def hook_func(request: httpx.Request):
    validate_url_safety(str(request.url))

async def main():
    async with httpx.AsyncClient(follow_redirects=True, event_hooks={"request": [hook_func]}) as client:
        try:
            await client.get("http://httpbin.org/redirect-to?url=http%3A%2F%2Fexample.com")
        except Exception as e:
            print(e)

asyncio.run(main())
