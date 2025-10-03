# syntax=docker/dockerfile:1
FROM python:3.11.9-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Instalamos dependencias con hashes reproducibles
COPY requirements.lock ./requirements.lock
RUN pip install --upgrade pip \
    && pip install --require-hashes -r requirements.lock

# Create unprivileged runtime user after dependencies are baked in
RUN groupadd --system app \
    && useradd --system --create-home --home-dir /home/app --gid app app

# Copiamos el código fuente
COPY . .

RUN chown -R app:app /app

USER app

ENV PYTHONPATH=/app/src

ENTRYPOINT ["python", "run_collector.py"]
CMD ["--help"]
