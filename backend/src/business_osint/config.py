"""Konfiguracja aplikacji (12-factor: wszystko z env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env leży w korzeniu repozytorium, a komendy uruchamia się i z korzenia,
    # i z backend/. Podajemy obie ścieżki, żeby konfiguracja nie zależała od tego,
    # skąd akurat startuje proces.
    model_config = SettingsConfigDict(
        env_file=(".env", str(Path(__file__).resolve().parents[3] / ".env")),
        env_prefix="BUSINESS_OSINT_",
        extra="ignore",
        frozen=True,
    )

    environment: str = "local"
    debug: bool = False

    database_url: PostgresDsn = Field(  # type: ignore[assignment]
        default="postgresql+asyncpg://osint:osint@localhost:5432/osint"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_statement_timeout_ms: int = 5_000

    # --- poświadczenia do rejestrów (puste = źródło wyłączone) ---
    #: Klucz do API GUS BIR1 (REGON). Bezpłatny, wniosek do GUS.
    regon_api_key: str = ""
    #: Token do API CEIDG v2. Bezpłatny, rejestracja w biznes.gov.pl.
    ceidg_token: str = ""

    #: Pepper do hashowania PESEL. W produkcji z sekretów, nigdy z repo.
    pesel_pepper: str = "change-me-in-production"

    cors_origins: list[str] = ["http://localhost:3000"]

    #: Domyślny plan dla anonimowego ruchu (limity grafu — patrz domain/graph_budget.py).
    default_plan: str = "free"

    @property
    def has_regon_access(self) -> bool:
        return bool(self.regon_api_key.strip())

    @property
    def has_ceidg_access(self) -> bool:
        return bool(self.ceidg_token.strip())

    @property
    def sync_database_url(self) -> str:
        """URL dla Alembica (psycopg) — migracje jadą synchronicznie."""
        return str(self.database_url).replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
