"""Application settings.

The repo-root ``.env`` defines ``openai_key``. We read that name explicitly (and
fall back to the SDK's standard ``OPENAI_API_KEY``), then export the resolved key
so both ``langchain-openai`` and the raw ``openai`` SDK pick it up.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]  # .../backend
REPO_ROOT = BACKEND_DIR.parent  # repo root (holds .env)
DATA_DIR = BACKEND_DIR / "app" / "data"
LOG_DIR = BACKEND_DIR / "logs"


class Settings(BaseSettings):
    # Secrets / model — accept either `openai_key` or the standard `OPENAI_API_KEY`.
    openai_key: str = Field(default="", validation_alias=AliasChoices("openai_key", "openai_api_key"))
    agent_model: str = "gpt-4o"  # override with AGENT_MODEL (e.g. gpt-4o-mini, gpt-4.1)

    # LangSmith tracing (optional) — activates LangChain/LangGraph tracing when a key is set.
    langsmith_tracing: bool = Field(
        default=True, validation_alias=AliasChoices("langsmith_tracing", "langchain_tracing_v2")
    )
    langsmith_api_key: str = Field(
        default="", validation_alias=AliasChoices("langsmith_api_key", "langchain_api_key")
    )
    langsmith_project: str = Field(
        default="loopp-refund-agent", validation_alias=AliasChoices("langsmith_project", "langchain_project")
    )
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        validation_alias=AliasChoices("langsmith_endpoint", "langchain_endpoint"),
    )

    # Policy knobs (single source of truth for the deterministic engine)
    return_window_days: int = 30
    escalation_threshold_usd: float = 500.0

    # Agent behaviour
    max_agent_iterations: int = 8

    # Infra
    db_path: str = str(DATA_DIR / "support.db")
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Accept the SDK's standard env var too, then export the resolved key so both
    # langchain-openai and the raw openai SDK pick it up.
    if not settings.openai_key:
        settings.openai_key = os.environ.get("OPENAI_API_KEY", "")
    if settings.openai_key and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.openai_key
    # Activate LangSmith tracing if a key is configured (sets the env vars the SDK reads).
    if settings.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
        os.environ.setdefault("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)
        os.environ.setdefault("LANGSMITH_TRACING", "true" if settings.langsmith_tracing else "false")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return settings
