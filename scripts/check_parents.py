from pathlib import Path
p = Path(r"c:\Users\corte\VS Code Projects\noticiencias_news_collector\noticiencias\config_manager.py")
print(f"Path: {p}")
print(f"Parents[0]: {p.parents[0]}")
print(f"Parents[1]: {p.parents[1]}")
try:
    print(f"Parents[2]: {p.parents[2]}")
except IndexError:
    print("Parents[2]: Index Error")
