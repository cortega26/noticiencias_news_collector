# syntax=docker/dockerfile:1

# ----------------------------------------------------------------------------------
# STAGE 1: Builder
# ----------------------------------------------------------------------------------
FROM python:3.11.9-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install system dependencies required for building wheels (if any)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a temporary directory to copy later
COPY requirements.lock .
RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.lock

# ----------------------------------------------------------------------------------
# STAGE 2: Runtime
# ----------------------------------------------------------------------------------
FROM python:3.11.9-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Create unprivileged generic user
RUN groupadd --system app && \
    useradd --system --create-home --home-dir /home/app --gid app app

# Install Runtime dependencies (e.g. libpq for Postgres if needed)
# Added curl for healthchecks if we use curl-based healthchecks later
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.lock .

# Install dependencies from wheels
RUN pip install --no-cache /wheels/*

# Copy source code
COPY . .

# Change ownership to app user
RUN chown -R app:app /app

# Switch to non-root user
USER app

# Healthcheck
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "scripts/healthcheck.py", "--max-pending", "500"]

# Default command (can be overridden)
CMD ["python", "run_collector.py", "--help"]
