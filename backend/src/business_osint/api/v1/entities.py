from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from business_osint.api.deps import SessionDep
from business_osint.repositories.entities import EntityRepository
from business_osint.schemas.entity import EntityProfileOut, IdentifierOut, RelationshipOut

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("/{entity_id}", response_model=EntityProfileOut, summary="Profil podmiotu")
async def get_entity(session: SessionDep, entity_id: uuid.UUID) -> EntityProfileOut:
    profile = await EntityRepository(session).get_profile(entity_id)
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
        updated_at=profile.get("updated_at"),
    )


@router.get(
    "/{entity_id}/relationships",
    response_model=list[RelationshipOut],
    summary="Powiązania podmiotu wraz ze źródłem każdej informacji",
)
async def get_relationships(
    session: SessionDep,
    entity_id: uuid.UUID,
    include_historical: Annotated[
        bool, Query(description="Pokaż też zakończone powiązania")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[RelationshipOut]:
    rows = await EntityRepository(session).relationships(
        entity_id, include_historical=include_historical, limit=limit
    )
    return [
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
