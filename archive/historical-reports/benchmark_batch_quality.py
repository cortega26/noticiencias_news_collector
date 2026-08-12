import json
import logging
import shutil
import sys
import time
from pathlib import Path

# Setup paths
sys.path.append(str(Path.cwd()))
from benchmark_articles import ALL_ARTICLES

from news_collector.components.editorial.ai_editor import EditorAgent

# Configure Logger to show info
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(message)s")
logger = logging.getLogger("benchmark")

# Scenarios for Batch Mode (High Latency Allowed)
SCENARIOS = {
    # Scenario A: Maximum Quality (Everything is 70B except headlines)
    # "A_MaxQuality": {
    #     "model": "llama3.3:latest",
    #     "translator_model": "llama3.3:latest",
    #     "editor_model": "llama3.3:latest",
    #     "headlines_model": "llama3.2:latest"
    # },
    # Scenario B: Balanced High Quality (Qwen 14B)
    "B_Balanced": {
        "model": "qwen2.5:14b",
        "translator_model": "qwen2.5:14b",
        "editor_model": "qwen2.5:14b",
        "headlines_model": "llama3.2:latest",
    },
    # Scenario C: Hybrid (Translator Heavy)
    # "C_Hybrid": {
    #     "model": "llama3.3:latest",
    #     "translator_model": "llama3.3:latest",
    #     "editor_model": "qwen2.5:14b",
    #     "headlines_model": "llama3.2:latest"
    # }
}

OUTPUT_DIR = Path("bench_results_batch")
OUTPUT_DIR.mkdir(exist_ok=True)


def clear_cache():
    cache_dir = Path("temp/cache")
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Cache cleared.")


def run_benchmark():
    results = []  # List of dicts

    print(
        f"Starting Batch Benchmark across {len(SCENARIOS)} scenarios and {len(ALL_ARTICLES)} articles."
    )
    print("NOTE: Timeouts extended to 3600s (60m) per article.")

    for sc_name, sc_config in SCENARIOS.items():
        print("\n" + "=" * 50)
        print(f"[Scenario: {sc_name}]")
        print("=" * 50)

        # Instantiate Agent
        try:
            agent = EditorAgent(
                api_url="http://localhost:11434/api/generate",
                model=sc_config["model"],
                translator_model=sc_config["translator_model"],
                editor_model=sc_config["editor_model"],
                headlines_model=sc_config["headlines_model"],
            )
            # FORCE TIMEOUT override for Batch Mode
            agent.provider.timeout = 3600

        except Exception as e:
            print(f"FAILED to instantiate agent for {sc_name}: {e}")
            continue

        for article in ALL_ARTICLES:
            art_id = article["id"]
            print(f"\n  > Processing {art_id} ({sc_name})...")

            # CLEAR CACHE to ensure full run
            clear_cache()

            start_t = time.time()
            try:
                output = agent.process_article(article["content"])
                duration = time.time() - start_t

                print(f"  > DONE ({duration:.2f}s)")

                # Save Output
                filename = OUTPUT_DIR / f"{sc_name}_{art_id}.md"
                filename.write_text(output, encoding="utf-8")

                results.append(
                    {
                        "scenario": sc_name,
                        "article": art_id,
                        "duration": duration,
                        "status": "OK",
                    }
                )

            except Exception as e:
                duration = time.time() - start_t
                print(f"  > FAILED ({duration:.2f}s): {e}")
                results.append(
                    {
                        "scenario": sc_name,
                        "article": art_id,
                        "duration": duration,
                        "status": f"ERROR: {e}",
                    }
                )

    # Summary Table
    print("\n" + "=" * 60)
    print("BATCH BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"{'Scenario':<15} | {'Article':<10} | {'Time (s)':<10} | {'Status'}")
    print("-" * 60)
    for r in results:
        print(
            f"{r['scenario']:<15} | {r['article']:<10} | {r['duration']:<10.2f} | {r['status']}"
        )

    # Save raw json for parsing
    Path("benchmark_batch_summary.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    run_benchmark()
