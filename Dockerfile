# syntax=docker/dockerfile:1
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Instalamos dependencias con hashes reproducibles
COPY requirements.lock ./requirements.lock
RUN pip install --upgrade pip \
    && pip install --require-hashes -r requirements.lock

# Copiamos el código fuente
COPY . .

ENV PYTHONPATH=/app/src

ENTRYPOINT ["python", "run_collector.py"]
CMD ["--help"]
