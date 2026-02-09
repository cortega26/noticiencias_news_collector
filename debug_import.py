
print("Start import os...")
import os
print("Start import sys...")
import sys
print("Start import ai_editor...")
try:
    from news_collector.components.editorial.ai_editor import EditorAgent
    print("Imported EditorAgent successfully.")
except Exception as e:
    print(f"Import failed: {e}")
