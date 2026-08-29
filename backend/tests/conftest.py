"""Wspólne fixture'y.

Testy integracyjne wymagają Postgresa (`docker compose up -d db`) i są
pomijane, gdy baza jest niedostępna — dzięki temu `pytest tests/unit`
działa wszędzie i w milisekundach.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.getenv(
    "BUSINESS_OSINT_TEST_DATABASE_URL",
    "postgresql+asyncpg://osint:osint@localhost:5432/osint_test",
)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as connection:
            await connection.rollback()
    except Exception as exc:  # pragma: no cover - zależy od środowiska
        pytest.skip(f"Postgres niedostępny: {exc}")

    from business_osint.db import models  # noqa: F401
    from business_osint.db.base import Base

    async with engine.begin() as connection:
        await connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await connection.run_sync(Base.metadata.create_all)
        await connection.exec_driver_sql(
            """
            CREATE OR REPLACE VIEW graph_edges AS
            SELECT id AS relationship_id, source_entity_id AS from_id,
                   target_entity_id AS to_id, 'out'::text AS direction,
                   relationship_type, role, valid_from, valid_to, recorded_at,
                   superseded_at, confidence, confidence_score, attributes
            FROM relationships
            UNION ALL
            SELECT id, target_entity_id, source_entity_id, 'in'::text,
                   relationship_type, role, valid_from, valid_to, recorded_at,
                   superseded_at, confidence, confidence_score, attributes
            FROM relationships
            """
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.info["engine"] = engine
        yield session

    async with engine.begin() as connection:
        await connection.exec_driver_sql("DROP VIEW IF EXISTS graph_edges")
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_engine(db_session):
    """Silnik tej samej bazy — potrzebny tam, gdzie test wymaga dwóch połączeń."""
    return db_session.info["engine"]
