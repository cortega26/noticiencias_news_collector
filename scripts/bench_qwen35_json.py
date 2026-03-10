#!/usr/bin/env python3
import sys
import time
from pathlib import Path

# Setup path so we can import news_collector
sys.path.append(str(Path.cwd()))
from news_collector.components.editorial.ai_editor import EditorAgent

# A moderately complex Spanish text to prompt for metadata extraction
TEST_ARTICLE = """
La misión Euclid de la Agencia Espacial Europea ha revelado hoy sus primeras imágenes científicas, demostrando su capacidad para observar miles de galaxias en una sola toma. Este telescopio espacial está diseñado para investigar la energía oscura y la materia oscura midiendo la aceleración del universo. Según el comunicado de la ESA, el nivel de detalle sin precedentes logrado por los instrumentos VIS y NISP permitirá crear el mapa 3D más grande del cosmos. Los científicos advierten que estos datos podrían cambiar nuestra comprensión fundamental de la física en los próximos diez años.
"""

MODELS_TO_TEST = [
    "qwen3.5:27b",
]

NUM_ITERATIONS = 1

def run_json_benchmark():
    # Silenciar logs masivos
    import logging
    logging.getLogger("news_collector").setLevel(logging.WARNING)

    print("==========================================================")
    print("   QWEN 3.5 MIGRATION A/B TEST: PYDANTIC STRICTNESS")
    print("==========================================================")
    print(f"Testing Stage 3: Headline Generation (Strict JSON mode)")
    print(f"Iterations per model: {NUM_ITERATIONS}")
    print("==========================================================\n")

    results = []

    for model_name in MODELS_TO_TEST:
        print(f">>> Evaluando Modelo: {model_name}")
        
        # Instantiate agent overriding the explicit models
        # We only care about headlines_model for this test, as it's the one doing the JSON/Pydantic validation
        agent = EditorAgent(
            api_url="http://localhost:11434/api/generate",
            model="llama3.2:latest", # Dummy base
            headlines_model=model_name
        )
        
        success_count = 0
        error_count = 0
        total_time = 0.0

        for i in range(1, NUM_ITERATIONS + 1):
            print(f"  [Iteración {i}/{NUM_ITERATIONS}] ", end="")
            start_t = time.time()
            
            try:
                # Stage 3 directly invokes Pydantic Validation on JSON generated
                print("(procesando...) ", end="", flush=True)
                result = agent._generate_headlines(TEST_ARTICLE)
                duration = time.time() - start_t
                total_time += duration
                success_count += 1
                keys_str = ", ".join(result.keys()) if isinstance(result, dict) else "Formato devuelto no es dict"
                print(f"✅ OK ({duration:.2f}s) - Keys encontradas: {keys_str}")
                
            except Exception as e:
                duration = time.time() - start_t
                total_time += duration
                error_count += 1
                print(f"❌ FALLO PYDANTIC ({duration:.2f}s): {e}")

        # Summary
        avg_time = total_time / NUM_ITERATIONS
        success_rate = (success_count / NUM_ITERATIONS) * 100
        
        results.append({
            "model": model_name,
            "success_rate": success_rate,
            "avg_latency": avg_time,
            "errors": error_count
        })
        print(f"\n✅ {model_name} -> Tasa de Éxito Pydantic: {success_rate:.1f}% | Latencia Media: {avg_time:.2f}s\n")

    print("==========================================================")
    print("                     RESUMEN FINAL                        ")
    print("==========================================================")
    print(f"{'Modelo':<15} | {'Éxito %':<10} | {'Latencia (s)':<15} | {'Errores JSON'}")
    print("-" * 60)
    for r in results:
        print(f"{r['model']:<15} | {r['success_rate']:<10.1f} | {r['avg_latency']:<15.2f} | {r['errors']}")
    print("==========================================================")


if __name__ == "__main__":
    run_json_benchmark()
