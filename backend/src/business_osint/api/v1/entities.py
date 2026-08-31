from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from business_osint.api.deps import SessionDep
from business_osint.repositories.entities import EntityRepository
from business_osint.schemas.entity import (
    EntityProfileOut,
    FinancialReportOut,
    IdentifierOut,
    LocationOut,
    PageMeta,
    RelationshipOut,
    RelationshipPageOut,
)

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("/{entity_id}", response_model=EntityProfileOut, summary="Profil podmiotu")
async def get_entity(session: SessionDep, entity_id: uuid.UUID) -> EntityProfileOut:
    repository = EntityRepository(session)
    profile = await repository.get_profile(entity_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nie znaleziono podmiotu")
    return EntityProfileOut(
        id=profile["id"],
        type=profile["entity_type"],
        name=profile["display_name"],
        degree=profile["degree"],
        identifiers=[IdentifierOut(**i) for i in profile.get("identifiers") or []],
        company=profile.get("company"),
        person=profile.get("person"),
        address=profile.get("address"),
        financials=[FinancialReportOut(**row) for row in await repository.financials(entity_id)],
        updated_at=profile.get("updated_at"),
    )


@router.get(
    "/{entity_id}/relationships",
    response_model=RelationshipPageOut,
    summary="Powiązania podmiotu wraz ze źródłem każdej informacji",
)
async def get_relationships(
    session: SessionDep,
    entity_id: uuid.UUID,
    include_historical: Annotated[
        bool, Query(description="Pokaż też zakończone powiązania")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RelationshipPageOut:
    repo = EntityRepository(session)
    total = await repo.count_relationships(entity_id, include_historical=include_historical)
    rows = await repo.relationships(
        entity_id, include_historical=include_historical, limit=limit, offset=offset
    )
    items = [
        RelationshipOut(
            id=row["relationship_id"],
            direction=row["direction"],
            type=row["relationship_type"],
            role=row["role"],
            other_id=row["other_id"],
            other_type=row["other_type"],
            other_name=row["other_name"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            confidence=row["confidence"],
            attributes=row["attributes"] or {},
            provenance=row["provenance"] or [],
        )
        for row in rows
    ]
    return RelationshipPageOut(
        items=items,
        meta=PageMeta(
            limit=limit,
            offset=offset,
            returned=len(items),
            has_more=offset + len(items) < total,
            total=total,
        ),
    )


@router.get(
    "/{entity_id}/location",
    summary="Współrzędne adresu — geokodowane raz i zapamiętane",
    description=(
        "Zwraca współrzędne adresu podmiotu. Pierwsze wywołanie odpytuje Nominatim "
        "i zapisuje wynik; kolejne czytają z bazy. Nominatim dopuszcza jedno zapytanie "
        "na sekundę, więc geokodujemy każdy adres najwyżej raz."
    ),
)
async def get_location(session: SessionDep, entity_id: uuid.UUID) -> LocationOut:
    location = await EntityRepository(session).locate(entity_id)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nie udało się ustalić lokalizacji")
    return LocationOut(**location)


@router.post(
    "/{entity_id}/enrich/krs",
    summary="Dociąga odpis KRS, jeśli jest starszy niż czas życia",
)
async def enrich_krs(entity_id: uuid.UUID, force: bool = False) -> dict[str, Any]:
    """Wzbogaca podmiot odpisem pełnym z KRS.

    Metoda POST, bo to **skutek uboczny**: pobranie z rejestru i zapis do bazy.
    GET, który po cichu odpytuje ministerstwo, byłby kłamstwem wobec każdego
    pośrednika, który uzna go za bezpieczny do powtórzenia.

    Nie zwraca błędu HTTP przy awarii rejestru. Wzbogacanie jest dodatkiem do
    profilu, który i tak się wyświetli — status pobrania wraca w treści.
    """
    from business_osint.etl.krs_enrichment import enrich_entity

    return (await enrich_entity(entity_id, force=force)).as_dict()
