from __future__ import annotations

from setuptools import setup

from config.version import PROJECT_VERSION, PYTHON_REQUIRES_SPECIFIER

if __name__ == "__main__":
    setup(
        name="noticiencias-news-collector",
        version=PROJECT_VERSION,
        python_requires=PYTHON_REQUIRES_SPECIFIER,
    )
