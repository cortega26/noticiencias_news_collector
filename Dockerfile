# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    UV_LINK_MODE=copy \
    HF_HOME=/root/.cache/huggingface

WORKDIR /app

COPY requirements.txt requirements.txt

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cache/huggingface \
    uv venv "${UV_PROJECT_ENVIRONMENT}" && \
    uv pip sync --python "${UV_PROJECT_ENVIRONMENT}/bin/python" requirements.txt

COPY . .

CMD ["python", "main.py"]
