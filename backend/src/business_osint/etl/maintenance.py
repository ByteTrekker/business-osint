"""Zadania utrzymaniowe uruchamiane po każdym większym imporcie."""

from __future__ import annotations

from sqlalchemy import text

from business_osint.db.session import get_sessionmaker

#: Przelicza entities.degree jednym zapytaniem zamiast COUNT(*) przy każdym odczycie.
#: Przy 50 mln krawędzi trwa to kilkadziesiąt sekund — uruchamiamy po imporcie,
#: a nie w ścieżce zapytania użytkownika.
_RECOMPUTE_DEGREES = text(
    """
    WITH d AS (
        SELECT entity_id, count(*) AS degree
        FROM (
            SELECT source_entity_id AS entity_id FROM relationships WHERE superseded_at IS NULL
            UNION ALL
            SELECT target_entity_id FROM relationships WHERE superseded_at IS NULL
        ) x
        GROUP BY entity_id
    )
    UPDATE entities e
    SET degree = COALESCE(d.degree, 0), updated_at = now()
    FROM d
    WHERE e.id = d.entity_id AND e.degree IS DISTINCT FROM d.degree
    """
)


async def recompute_degrees() -> int:
    async with get_sessionmaker()() as session, session.begin():
        result = await session.execute(_RECOMPUTE_DEGREES)
        return result.rowcount or 0
