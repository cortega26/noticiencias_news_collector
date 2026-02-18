FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (global location)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN mkdir /ms-playwright && playwright install --with-deps chromium

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /ms-playwright /app
USER appuser

# Copy application code (chown for rw access if needed, though usually code is ro)
COPY --chown=appuser:appuser . .

# Environment Defaults
ENV RUN_ENVIRONMENT=production
ENV ENABLE_HEADLESS=true
ENV COLLECTION_INTERVAL_SECONDS=600

# Entrypoint
CMD ["python3", "scripts/run_collector_continuous.py"]
