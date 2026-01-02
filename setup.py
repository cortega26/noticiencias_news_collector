from pathlib import Path

from setuptools import find_packages, setup

from news_collector.config.version import PYTHON_REQUIRES_SPECIFIER

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
        python_requires=PYTHON_REQUIRES_SPECIFIER,
    )
