# Loopp Refund Agent — Backend

FastAPI + LangGraph service hosting the refund agent. See the top-level [`README.md`](../README.md) for full setup and demo instructions.

```bash
uv sync
uv run python -m app.db.seed
uv run uvicorn app.main:app --reload --port 8000
```
