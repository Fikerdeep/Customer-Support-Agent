# Backend: FastAPI + LangGraph, managed with uv.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Install dependencies first (cached layer).
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev

# App code.
COPY app ./app

EXPOSE 8000
# Shell form so $PORT (injected by hosts like Render) is honored; defaults to 8000 (compose/local).
CMD uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
