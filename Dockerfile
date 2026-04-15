FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies using hash-pinned lockfiles (see ADR-0002)
COPY requirements.lock requirements-security.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
 && pip install --no-cache-dir --require-hashes -r requirements-security.lock

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

# Entrypoint — preferred CLI entrypoint (see README.md "Preferred Entry Points")
CMD ["python", "scripts/run_collector.py"]
