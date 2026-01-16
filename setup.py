from pathlib import Path

from setuptools import find_packages, setup

# from news_collector.config.version import PYTHON_REQUIRES_SPECIFIER

# Read version without importing the package
def read_version():
    root = Path(__file__).resolve().parent
    version_file = root / "news_collector" / "config" / "VERSION"
    return version_file.read_text().strip()

PROJECT_VERSION = read_version()

if __name__ == "__main__":
    setup(
        name="noticiencias-news-collector",
        version=PROJECT_VERSION,
        packages=find_packages(),
        python_requires=">=3.10",
        install_requires=[
            "aiohttp>=3.9.0",
            "feedparser>=6.0.0",
            "requests>=2.0.0",
            # Add other known dependencies if they were missing, but primarily aiohttp for this task
        ],
    )
