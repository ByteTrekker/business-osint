from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from business_osint.api.deps import SessionDep
from business_osint.repositories.entities import EntityRepository
from business_osint.schemas.entity import PageMeta, SearchHitOut, SearchResultOut

router = APIRouter(tags=["search"])

#: Najgłębsze dopuszczalne przesunięcie. Wyszukiwarka jest etapowa i żeby oddać
#: stronę n, musi pobrać wszystko, co ją poprzedza. Przy tysiącu to nadal
#: milisekundy; bez ograniczenia byłoby to zaproszenie do wysycenia bazy jednym
#: żądaniem. Kto potrzebuje więcej niż tysiąc wyników, potrzebuje eksportu,
#: a nie przewijania.
MAX_OFFSET = 1000


@router.get("/search", response_model=SearchResultOut, summary="Wyszukiwarka podmiotów i osób")
async def search(
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=200, description="Nazwa, NIP, KRS lub REGON")],
    type: Annotated[str | None, Query(description="Filtr typu encji")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[
        int,
        Query(
            ge=0,
            le=MAX_OFFSET,
            description=(
                "Przesunięcie w wynikach. Ograniczone, bo wyszukiwarka jest etapowa "
                "i głębsze strony wymagałyby pobrania wszystkiego, co je poprzedza."
            ),
        ),
    ] = 0,
    fuzzy: Annotated[
        bool,
        Query(description="Dopasowanie rozmyte — wolniejsze, włączane świadomie"),
    ] = False,
) -> SearchResultOut:
    hits, has_more = await EntityRepository(session).search(
        q, entity_type=type, limit=limit, offset=offset, fuzzy=fuzzy
    )
    return SearchResultOut(
        query=q,
        meta=PageMeta(limit=limit, offset=offset, returned=len(hits), has_more=has_more),
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
