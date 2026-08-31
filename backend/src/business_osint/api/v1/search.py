from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from business_osint.api.deps import SessionDep
from business_osint.repositories.entities import EntityRepository
from business_osint.schemas.entity import SearchHitOut, SearchResultOut

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResultOut, summary="Wyszukiwarka podmiotów i osób")
async def search(
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=200, description="Nazwa, NIP, KRS lub REGON")],
    type: Annotated[str | None, Query(description="Filtr typu encji")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    fuzzy: Annotated[
        bool,
        Query(description="Dopasowanie rozmyte — wolniejsze, włączane świadomie"),
    ] = False,
) -> SearchResultOut:
    hits = await EntityRepository(session).search(q, entity_type=type, limit=limit, fuzzy=fuzzy)
    return SearchResultOut(
        query=q,
        hits=[
            SearchHitOut(
                id=h.id,
                type=h.entity_type,
                name=h.display_name,
                subtitle=h.subtitle,
                score=h.score,
                degree=h.degree,
            )
            for h in hits
        ],
    )
