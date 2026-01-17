
import sys
import noticiencias.config_schema
import noticiencias.config_manager

print(f"Python Executable: {sys.executable}")
print(f"config_schema path: {noticiencias.config_schema.__file__}")
print(f"config_manager path: {noticiencias.config_manager.__file__}")

try:
    from noticiencias.config_schema import Config
    cfg = Config()
    # Attempt to access github
    print(f"Config().github type: {type(cfg.github)}")
except Exception as e:
    print(f"Failed to access Config().github: {e}")
