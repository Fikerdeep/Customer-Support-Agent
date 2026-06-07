"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, chat
from app.core.config import get_settings
from app.core.observability import configure_logging
from app.db.database import SessionLocal, init_db
from app.db.models import Customer
from app.db.seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    # Zero-config: auto-seed the mock CRM on first boot if the DB is empty.
    db = SessionLocal()
    try:
        if db.query(Customer).count() == 0:
            seed()
    finally:
        db.close()
    yield


settings = get_settings()
app = FastAPI(title="Loopp Refund Agent API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(admin.router)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "provider": "openai",
        "model": settings.agent_model,
        "api_key_configured": bool(settings.openai_key),
        "langsmith_tracing": bool(settings.langsmith_api_key) and settings.langsmith_tracing,
        "langsmith_project": settings.langsmith_project if settings.langsmith_api_key else None,
    }
