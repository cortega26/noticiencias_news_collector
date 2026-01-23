import importlib.util
import sys

REQUIRED_PACKAGES = [
    "streamlit",
    "pandas",
    "git",  # GitPython
    "yaml",  # PyYAML
    "toml",
    "requests",  # Standard
    "dotenv",  # python-dotenv
]


def check_imports():
    print("🔍 Checking environment dependencies...")
    missing = []
    for pkg in REQUIRED_PACKAGES:
        spec = importlib.util.find_spec(pkg)
        if spec is None:
            missing.append(pkg)
            print(f"❌ Missing: {pkg}")
        else:
            print(f"✅ Found: {pkg}")

    if missing:
        print("\n⚠️  Environment Incomplete. Please run:")
        print("    pip install -r requirements.txt")
        sys.exit(1)
    else:
        print("\n✅ Environment looks good!")
        sys.exit(0)


if __name__ == "__main__":
    check_imports()
