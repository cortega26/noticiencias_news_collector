import asyncio
from news_collector.config.settings import CONFIG
from news_collector.infrastructure.llm.factory import get_provider
import time

async def main():
    print(f"Gemini API string: {getattr(CONFIG.gemini, 'api_key', 'NONE')[:5]}...")
    provider = get_provider(config=CONFIG)
    
    print("Spamming to hit rate limit...")
    for i in range(5):
        try:
            start = time.time()
            res = provider.generate_sync(f"Say 'Hello {i}'", timeout=10)
            print(f"Attempt {i} Success in {time.time()-start:.2f}s: {res}")
        except Exception as e:
            print(f"Attempt {i} FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(main())
