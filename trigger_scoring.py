import asyncio
import logging
from news_collector.system import create_system

# Configure logging to see output
logging.basicConfig(level=logging.INFO)

async def trigger_run():
    print("--- Triggering Collection Cycle (Scoring Pending Articles) ---")
    system = create_system()
    if system.initialize():
        # Run cycle. This will:
        # 1. Collect (might skip sources if recent)
        # 2. Score (will pick up 70 pending articles)
        # 3. Export
        report = await system.run_collection_cycle()

        print("\n--- Report Summary ---")
        summary = report.get("summary", {})
        print(f"Articles Scored: {summary.get('articles_scored')}")
        print(f"Final Selection: {summary.get('final_selection_count')}")

        if summary.get('articles_scored', 0) > 0:
            print("✅ SUCCESS: Articles were scored!")
        else:
            print("❌ FAILURE: No articles scored.")
    else:
        print("❌ Failed to initialize system.")

if __name__ == "__main__":
    asyncio.run(trigger_run())
