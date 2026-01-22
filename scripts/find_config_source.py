import os
import sys

try:
    import noticiencias.config_manager

    print(f"CONFIG_MANAGER_PATH: {noticiencias.config_manager.__file__}")
except ImportError:
    print("Could not import noticiencias.config_manager")
except Exception as e:
    print(f"Error: {e}")
