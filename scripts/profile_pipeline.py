import asyncio
import time
from unittest.mock import patch

from sqlalchemy import event
from sqlalchemy.engine import Engine

from news_collector.system import NewsCollectorSystem

query_count = 0


@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    global query_count
    query_count += 1


async def run_baseline():
    print("Initializing system for profiling...")
    system = NewsCollectorSystem()
    system.initialize()

    print("Starting collection cycle...")
    start_time = time.perf_counter()

    # We limit to a single source
    result = await system.run_collection_cycle(dry_run=False, sources_filter=["wired"])

    end_time = time.perf_counter()
    duration = end_time - start_time

    print("\n--- PERFORMANCE SNAPSHOT ---")
    print(f"Cycle Duration: {duration:.3f} s")
    print(f"Total DB Queries executed during cycle: {query_count}")
    print("Results:")

    if result.get("success"):
        print(
            f"- Articles Collected: {result.get('collection_summary', {}).get('articles_saved', 0)}"
        )
        print(
            f"- Articles Scored: {result.get('scoring_summary', {}).get('statistics', {}).get('articles_scored', 0)}"
        )
    else:
        print(f"Cycle failed: {result}")


if __name__ == "__main__":
    asyncio.run(run_baseline())
