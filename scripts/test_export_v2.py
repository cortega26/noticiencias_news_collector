
import sys
import os
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from news_collector.system import create_system
import asyncio

async def main():
    print("Initializing system...")
    system = create_system()
    if not system.initialize():
        print("Failed to initialize system")
        sys.exit(1)
    
    print("Exporting latest articles...")
    try:
        # Export
        output_path = project_root / "data/exports/latest_articles_v2.json"
        res = system.export_latest_articles(file_path=str(output_path), limit=5)
        print(f"Export successful to {output_path}")
        print(f"Schema Version: {res.get('schema_version')}")
        print(f"Version: {res.get('version')}")
    except Exception as e:
        print(f"Export failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
