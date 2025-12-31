from setuptools import setup, find_packages
from pathlib import Path

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
        python_requires=">=3.10", # Hardcoding for safety or reading properly if complex logic needed
        packages=find_packages(),
        install_requires=[
            "feedparser>=6.0.12",
            "requests>=2.32.5",
            "beautifulsoup4>=4.14.2",
            "lxml>=6.0.2",
            "nltk>=3.9.2",
            "textblob>=0.19.0",
            "python-dateutil>=2.9.0",
            "sqlalchemy>=2.0.43",
            "python-dotenv>=1.1.1",
            "schedule>=1.2.2",
            "click>=8.3.0",
            "ruamel.yaml>=0.18.6",
            "tomli-w>=1.0.0",
            "fastapi>=0.118.0",
            "pydantic>=2.11.9",
            "loguru>=0.7.3",
            "httpx>=0.28.1",
            "scikit-learn>=1.7.2",
            "numpy>=2.3.3",
            "streamlit>=1.30.0",
            "gitpython>=3.1.41",
            "watchdog>=4.0.0",
            "toml>=0.10.2",
        ],
        extras_require={
            "test": [
                "pytest>=8.4.2",
                "pytest-cov>=7.0.0",
                "hypothesis>=6.104.1",
                "mutmut>=3.3.1",
            ],
        },
    )
