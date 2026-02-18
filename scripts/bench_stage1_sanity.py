import shutil
import sys
import time
from pathlib import Path

# Fix path to allow imports
sys.path.append(str(Path.cwd()))
from news_collector.components.editorial.ai_editor import EditorAgent

# 2. Medium Article (~800 chars content, ~1000 with titles) from previous benchmark
ARTICLE_MEDIUM = {
    "title": "New Species of 'Silent' Frog Discovered in Cloud Forests",
    "content": """
    Biologists exploring the dense cloud forests of the Andes have identified a remarkable new species of frog that does not croak. Unlike most anurans that rely on vocal calls to attract mates, this species, named *Centrolene mutum*, appears to communicate using visual signaling.

    The discovery was made during a three-week expedition to a remote valley previously inaccessible due to rough terrain. "We noticed them waving their hands," said Dr. Elena Gomez, the lead herpetologist. "It's a behavior known as foot-flagging, often seen in species living near loud waterfalls, but these frogs live in quiet streams."

    Genetic analysis confirms that *C. mutum* is distinct from its closest relatives, diverging approximately 2 million years ago. The frogs possess translucent skin on their undersides, a characteristic of glass frogs, revealing their beating hearts.

    Conservationists are urging for immediate protection of the area. The valley is currently threatened by illegal logging operations. "This species is a clear indicator of the region's biodiversity," noted Gomez. "If we lose the forest, we lose a lineage that evolved a unique solution to communication."

    The team plans to return next year to study the frog's mating rituals in detail and assess the population size. Early estimates suggest fewer than 500 individuals remain in the wild.
    """,
}

MODELS = [
    "llama3.2:latest",  # Baseline (Fast)
    "qwen2.5:14b",  # Suspect (Slow?)
]


def clear_cache():
    cache_dir = Path("temp/cache")
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    print("CACHE=OFF (sanity run) - Cache cleared.")


def bench():
    print("--- Microbenchmark Stage 1 Sanity ---")

    # Pre-calculate input string exactly as EditorAgent constructs it
    title = ARTICLE_MEDIUM["title"]
    content = ARTICLE_MEDIUM["content"]
    formatted_input = f"Title: {title}\nContent: {content}"

    # sys_prompt = "Translate to Spanish. Keep it neutral."  # Unused
    # Note: We rely on EditorAgent's internal prompt loading,
    # but we can verify what it sends via the debug hook.

    results = []

    for model_name in MODELS:
        print(f"\n>>> Testing Model: {model_name}")

        # Instantiate with specific model for translator
        agent = EditorAgent(
            api_url="http://localhost:11434/api/generate",
            model=model_name,
            translator_model=model_name,  # Force this model
            editor_model="llama3.2:latest",
            headlines_model="llama3.2:latest",
        )
        # Increase timeout heavily just in case, though we want to measure actual time
        agent.provider.timeout = 3600

        # Run twice
        for i in range(1, 3):
            print(f"  [Run {i}]")
            clear_cache()

            start_t = time.time()
            try:
                # We call _translate_scientific directly to isolate Stage 1
                # This matches step 2 requirements
                output = agent._translate_scientific(formatted_input)
                duration = time.time() - start_t

                in_chars = len(formatted_input)
                out_chars = len(output)

                print(f"  Result: {duration:.2f}s | In: {in_chars} | Out: {out_chars}")

                runaway = "NO"
                if out_chars > in_chars * 6 or out_chars > 20000:
                    runaway = "YES"
                    print(f"  [ALERT] Runaway detected! {out_chars} chars.")

                results.append(
                    {
                        "model": model_name,
                        "run": i,
                        "input_chars": in_chars,
                        "output_chars": out_chars,
                        "seconds": duration,
                        "runaway": runaway,
                    }
                )

            except Exception as e:
                print(f"  FAILED: {e}")
                results.append(
                    {"model": model_name, "run": i, "status": "ERROR", "error": str(e)}
                )

    print("\n" + "=" * 60)
    print("SANITY RESULTS")
    print("=" * 60)
    print(
        f"{'Model':<15} | {'Run':<3} | {'In':<6} | {'Out':<6} | {'Time(s)':<8} | {'Runaway'}"
    )
    for r in results:
        if "error" in r:
            print(f"{r['model']:<15} | {r['run']:<3} | ERROR: {r['error']}")
        else:
            print(
                f"{r['model']:<15} | {r['run']:<3} | {r['input_chars']:<6} | {r['output_chars']:<6} | {r['seconds']:<8.2f} | {r['runaway']}"
            )


if __name__ == "__main__":
    bench()
