"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a request id to every request, expose it on the response, and log it."""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def _error_body(request: Request, message: str, type_: str) -> dict:
    return {
        "detail": message,
        "error": {"type": type_, "message": message},
        "request_id": getattr(request.state, "request_id", None),
    }


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    body = _error_body(request, str(exc.detail), "http_error")
    return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = _error_body(request, "Invalid request.", "validation_error")
    body["errors"] = exc.errors()
    return JSONResponse(status_code=422, content=body)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = getattr(request.state, "request_id", None)
    logging.getLogger("loopp.api").exception("unhandled_error request_id=%s: %s", rid, exc)
    body = _error_body(request, "Internal server error.", "internal_error")
    return JSONResponse(status_code=500, content=body)


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
