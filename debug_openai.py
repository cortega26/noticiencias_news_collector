
import asyncio
from playwright.async_api import async_playwright

async def debug_openai():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        url = "https://openai.com/research"
        print(f"Navigating to {url}...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print("Page loaded.")

            # Check for item selectors
            items = await page.query_selector_all("div.snap-start") # Old selector
            print(f"Items found with 'div.snap-start': {len(items)}")

            if len(items) > 0:
                first = items[0]
                # Try finding title with configured selector
                title_el = await first.query_selector("div.text-h5 p")
                if title_el:
                    print(f"Title found: {await title_el.inner_text()}")
                    print(f"Full item text: {await first.inner_text()}")
                else:
                    print("Title selector 'div.text-h5 p' FAILED.")
                    # Dump text content to guess selector
                    print(f"Item text content: {await first.inner_text()}")
                    # Dump inner HTML for precise debugging
                    print(f"Item inner HTML: {await first.inner_html()}")

        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_openai())
