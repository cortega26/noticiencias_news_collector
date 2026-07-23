"""
Entry point to run the Noticiencias HTTP serving layer.

Usage:
    python -m news_collector.serving
"""

from news_collector.serving.api import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "news_collector.serving.__main__:app",
        host="0.0.0.0",  # noqa: S104 — intended for local dev server
        port=8000,
        reload=True,
    )
