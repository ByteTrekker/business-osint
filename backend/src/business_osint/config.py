"""Konfiguracja aplikacji (12-factor: wszystko z env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="BUSINESS_OSINT_", extra="ignore", frozen=True
    )

    environment: str = "local"
    debug: bool = False

    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://osint:osint@localhost:5432/osint"  # type: ignore[arg-type]
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_statement_timeout_ms: int = 5_000

    #: Pepper do hashowania PESEL. W produkcji z sekretów, nigdy z repo.
    pesel_pepper: str = "change-me-in-production"

    cors_origins: list[str] = ["http://localhost:3000"]

    #: Domyślny plan dla anonimowego ruchu (limity grafu — patrz domain/graph_budget.py).
    default_plan: str = "free"

    @property
    def sync_database_url(self) -> str:
        """URL dla Alembica (psycopg) — migracje jadą synchronicznie."""
        return str(self.database_url).replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
