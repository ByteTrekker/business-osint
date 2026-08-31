"""Sesja bazy: async engine + zależność FastAPI."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from business_osint.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_etl_engine: AsyncEngine | None = None
_etl_sessionmaker: async_sessionmaker[AsyncSession] | None = None

#: Limit czasu instrukcji dla zadań ETL. Operacje masowe (COPY, przeliczanie
#: stopni, ładowanie milionów krawędzi) trwają minuty — limit 5 s właściwy dla
#: API zabijał je pięć razy z rzędu, zanim powstał ten osobny silnik.
ETL_STATEMENT_TIMEOUT_MS = 30 * 60 * 1000


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            str(settings.database_url),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            echo=settings.debug,
            # Twardy limit na zapytanie — zapytania grafowe potrafią uciec,
            # a wolne zapytanie ma umrzeć w bazie, nie w workerze.
            connect_args={
                "server_settings": {
                    "statement_timeout": str(settings.db_statement_timeout_ms),
                    "application_name": "business-osint-api",
                }
            },
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


def get_etl_engine() -> AsyncEngine:
    """Silnik dla zadań wsadowych — bez krótkiego limitu czasu instrukcji.

    API i ETL mają przeciwne wymagania: API chce, żeby zapytanie, które ucieka,
    umarło po pięciu sekundach; ETL potrzebuje minut na jedną instrukcję.
    Jeden silnik nie obsłuży obu, a `SET LOCAL` w każdej transakcji z osobna
    okazał się łatwiejszy do przeoczenia niż do zapamiętania.
    """
    global _etl_engine
    if _etl_engine is None:
        settings = get_settings()
        _etl_engine = create_async_engine(
            str(settings.database_url),
            pool_size=4,
            max_overflow=4,
            pool_pre_ping=True,
            connect_args={
                "server_settings": {
                    "statement_timeout": str(ETL_STATEMENT_TIMEOUT_MS),
                    "application_name": "business-osint-etl",
                }
            },
        )
    return _etl_engine


def get_etl_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _etl_sessionmaker
    if _etl_sessionmaker is None:
        _etl_sessionmaker = async_sessionmaker(get_etl_engine(), expire_on_commit=False)
    return _etl_sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker, _etl_engine, _etl_sessionmaker
    for engine in (_engine, _etl_engine):
        if engine is not None:
            await engine.dispose()
    _engine = None
    _sessionmaker = None
    _etl_engine = None
    _etl_sessionmaker = None
