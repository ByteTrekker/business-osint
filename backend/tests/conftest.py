"""Wspólne fixture'y.

Testy integracyjne wymagają Postgresa (`docker compose up -d db`) i są
pomijane, gdy baza jest niedostępna — dzięki temu `pytest tests/unit`
działa wszędzie i w milisekundach.
"""

from __future__ import annotations

import os
import pathlib
import sys
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.getenv(
    "BUSINESS_OSINT_TEST_DATABASE_URL",
    "postgresql+asyncpg://osint:osint@localhost:5432/osint_test",
)


#: Czyścimy wszystko poza `alembic_version` — schemat ma przetrwać, dane nie.
#: `RESTART IDENTITY` zeruje sekwencje, żeby identyfikatory w dzienniku zmian
#: były przewidywalne między testami.
_TRUNCATE_WSZYSTKO = """
    DO $$
    DECLARE tabele text;
    BEGIN
        SELECT string_agg(format('%I.%I', schemaname, tablename), ', ')
        INTO tabele
        FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'alembic_version';
        IF tabele IS NOT NULL THEN
            EXECUTE 'TRUNCATE ' || tabele || ' RESTART IDENTITY CASCADE';
        END IF;
    END $$;
"""


@pytest.fixture(scope="session")
def _zmigrowana_baza() -> str:
    """Buduje bazę testową **migracjami**, nie `create_all`.

    Powód jest konkretny i kosztował już jeden zestaw czerwonych testów.
    `Base.metadata.create_all` tworzy tabele i indeksy, ale nie wyzwalacze ani
    widoki — te istnieją wyłącznie w migracjach. Schemat testowy różnił się więc
    od produkcyjnego, a testy dziennika zmian przechodziły przez bazę, w której
    wyzwalaczy po prostu nie było.

    Wcześniej conftest nadrabiał to, przepisując widok `graph_edges` ręcznie.
    Dwie definicje tego samego obiektu rozjeżdżają się przy pierwszej zmianie —
    dokładnie ta klasa błędu, którą ten projekt spotkał już przy normalizacji
    adresów i przy fixture KRS.
    """
    import subprocess

    from sqlalchemy import create_engine, text

    sync_url = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg")
    try:
        engine = create_engine(sync_url)
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        engine.dispose()
    except Exception as exc:  # pragma: no cover - zależy od środowiska
        pytest.skip(f"Postgres niedostępny: {exc}")

    katalog = pathlib.Path(__file__).parent.parent
    # Pełna ścieżka do interpretera z venva, nie samo „alembic": lint słusznie
    # protestuje przeciw poleganiu na PATH, a `python -m` działa też wtedy, gdy
    # venv nie jest aktywowany w powłoce.
    wynik = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=katalog,
        env={**os.environ, "BUSINESS_OSINT_DATABASE_URL": TEST_DATABASE_URL},
        capture_output=True,
        text=True,
    )
    if wynik.returncode != 0:
        pytest.skip(f"Migracje bazy testowej nie przeszły:\n{wynik.stderr[-800:]}")
    return TEST_DATABASE_URL


@pytest_asyncio.fixture
async def db_session(_zmigrowana_baza: str) -> AsyncIterator:
    """Sesja na zmigrowanym schemacie, z czyszczeniem tabel po teście.

    Izolację daje `TRUNCATE`, a **nie** wycofanie transakcji. Wycofanie byłoby
    szybsze, ale ukrywa zapisy przed innymi połączeniami — a testy kolejki
    zadań sprawdzają właśnie zachowanie dwóch workerów na `SKIP LOCKED`
    i muszą widzieć nawzajem swoje commity.

    Schemat stawiamy raz na cały przebieg: odtwarzanie ośmiu migracji przy
    każdym teście kosztowałoby więcej niż same testy.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_zmigrowana_baza)
    async with engine.begin() as connection:
        await connection.execute(text(_TRUNCATE_WSZYSTKO))

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.info["engine"] = engine
        yield session

    async with engine.begin() as connection:
        await connection.execute(text(_TRUNCATE_WSZYSTKO))
    await engine.dispose()


@pytest_asyncio.fixture
async def db_engine(db_session):
    """Silnik tej samej bazy — potrzebny tam, gdzie test wymaga dwóch połączeń."""
    return db_session.info["engine"]
