"""
Entry point to run the Noticiencias HTTP serving layer.

Usage:
    python -m news_collector.serving
"""

import os

from news_collector.serving.api import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "news_collector.serving.__main__:app",
        host=os.environ.get("NOTICIENCIAS_API_HOST", "127.0.0.1"),
        port=8000,
        reload=True,
    )
