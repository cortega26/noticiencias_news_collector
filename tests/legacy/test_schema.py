import os
import sys

# Add project root
from pathlib import Path

BASE_DIR = Path(
    os.environ.get("NEWS_COLLECTOR_PATH", Path(__file__).resolve().parents[1])
).resolve()
sys.path.insert(0, str(BASE_DIR))

try:
    from noticiencias.config_schema import Config

    print(f"Inspecting Config keys: {list(Config.model_fields.keys())}")

    if "github" in Config.model_fields:
        print("✅ 'github' field IS present in Config schema.")
        try:
            cfg = Config()
            print(f"✅ Config instance created. github type: {type(cfg.github)}")
        except Exception as e:
            print(f"❌ Failed to instantiate Config: {e}")
    else:
        print("❌ 'github' field is MISSING from Config schema.")

except ImportError as e:
    print(f"❌ ImportError: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
