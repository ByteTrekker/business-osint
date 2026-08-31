"""Odcisk zbioru danych — do porównywania pomiarów wydajności.

Pomiar bez tego jest nieporównywalny. „Zapytanie zajmuje 6 ms" nic nie znaczy,
dopóki nie wiadomo, na ilu encjach; przyspieszenie o połowę po zmianie bazy
może być zasługą zmiany albo tego, że w międzyczasie ubyło danych.

Endpoint jest **częścią kontraktu**, a nie narzędziem diagnostycznym: benchmark
ma działać także wtedy, gdy backend zostanie przepisany na inny język, a baza
zamieniona na inną. Wtedy nowa implementacja musi to samo wystawić — i wtedy
te same pomiary dalej się ze sobą porównują.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from business_osint.api.deps import SessionDep

router = APIRouter(tags=["stats"])


class DatasetStats(BaseModel):
    """Rozmiar zbioru, na którym wykonano pomiar."""

    entities: int = Field(description="Encje nie scalone w inne")
    relationships: int = Field(description="Krawędzie obowiązujące")
    companies: int
    people: int
    addresses: int
    sources: int = Field(description="Rejestry, z których cokolwiek pobrano")
    schema_version: str | None = Field(
        default=None,
        description=(
            "Wersja migracji. Zmiana schematu między pomiarami zwykle znaczy, "
            "że porównujemy dwie różne aplikacje, a nie dwie wersje tej samej."
        ),
    )


# Jedno zapytanie zamiast siedmiu: odcisk pobiera się przed każdym przebiegiem
# pomiaru, więc nie może sam być kosztowny. Liczniki idą z `pg_class`… nie —
# celowo liczymy dokładnie, bo szacunki planera potrafią się mylić o kilkanaście
# procent, a odcisk ma rozstrzygać, czy dwa przebiegi są porównywalne.
_STATS = text("""
    SELECT
        (SELECT count(*) FROM entities WHERE merged_into_id IS NULL) AS entities,
        (SELECT count(*) FROM relationships WHERE superseded_at IS NULL) AS relationships,
        (SELECT count(*) FROM companies) AS companies,
        (SELECT count(*) FROM people) AS people,
        (SELECT count(*) FROM addresses) AS addresses,
        (SELECT count(*) FROM sources) AS sources,
        (SELECT version_num FROM alembic_version LIMIT 1) AS schema_version
""")


@router.get(
    "/stats",
    response_model=DatasetStats,
    summary="Rozmiar zbioru danych — odcisk do porównywania pomiarów",
)
async def get_stats(session: SessionDep) -> DatasetStats:
    row = (await session.execute(_STATS)).mappings().one()
    return DatasetStats(**row)
