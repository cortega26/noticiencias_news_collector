
import logging
import sys
import os
import time

# Configure logging
logging.basicConfig(level=logging.INFO)

# Dummy article content
TEXT_CONTENT = "X" * 1000  # 1000 chars

try:
    from news_collector.utils.llm_client import LLMClient
    
    print("Initializing LLMClient (should utilize llama3.2:1b)...")
    llm = LLMClient()
    print(f"Model: {llm.model}")
    
    system_prompt = (
        "Analyze this text and return JSON with keys: 'score' (0-10) and 'summary'."
    )
    
    print("\n--- Starting Benchmark ---")
    start = time.time()
    
    try:
        response = llm.generate(prompt=TEXT_CONTENT, system=system_prompt, format="json")
        duration = time.time() - start
        
        print(f"✅ Success!")
        print(f"⏱️ Duration: {duration:.2f} seconds")
        print(f"Response: {str(response)[:100]}...")
        
    except Exception as e:
        print(f"❌ Failed: {e}")

except Exception as e:
    print(f"❌ Critical Error: {e}")
