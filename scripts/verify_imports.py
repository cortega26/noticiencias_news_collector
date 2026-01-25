import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path.cwd()))

print("Testing imports...")

try:
    print("1. Importing NewsCollectorSystem from news_collector.system...")
    from news_collector.system import NewsCollectorSystem  # noqa: F401

    print("   -> Success")
except ImportError as e:
    print(f"   -> Failed: {e}")
    sys.exit(1)

try:
    print("2. Importing bootstrap module...")
    import news_collector.system.bootstrap  # noqa: F401

    print("   -> Success")
except ImportError as e:
    print(f"   -> Failed: {e}")
    sys.exit(1)

try:
    print("3. Importing pipeline module...")
    import news_collector.system.pipeline  # noqa: F401

    print("   -> Success")
except ImportError as e:
    print(f"   -> Failed: {e}")
    sys.exit(1)

print("\nImport verification complete. No immediate circular dependencies detected.")
