import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from news_collector.config.settings import SCORING_CONFIG, DATABASE_CONFIG

print(f"Scoring Mode: {SCORING_CONFIG.get('mode')}")
print(f"Database Path: {DATABASE_CONFIG.get('path')}")
print(f"Weights: {SCORING_CONFIG.get('weights')}")
