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
    status: Annotated[
        str | None,
        Query(
            pattern="^(active|suspended|inactive|partnership_only)$",
            description="Filtr stanu działalności; nie dotyczy szukania po identyfikatorze",
        ),
    ] = None,
    voivodeship: Annotated[
        str | None,
        Query(
            max_length=64,
            description=(
                "Filtr województwa. Zawężający: podmioty bez zapisanego "
                "województwa (wszystko spoza CEIDG) wypadają z wyniku, bo "
                "pytanie brzmi \u201ew tym wojew\u00f3dztwie\u201d, a nie "
                "\u201emo\u017ce w tym\u201d."
            ),
        ),
    ] = None,
    pkd: Annotated[
        str | None,
        Query(
            pattern=r"^[0-9]{2}\.?[0-9]{0,2}\.?[A-Z]?$",
            description=(
                "Filtr PKD po prefiksie: 62 to ca\u0142a informatyka, "
                "62.01.Z jedna klasa. Zaw\u0119\u017caj\u0105cy jak wojew\u00f3dztwo."
            ),
        ),
    ] = None,
    sort: Annotated[
        str,
        Query(
            pattern="^(relevance|degree|name|registered|city|status)$",
            description=(
                "Porządek wyniku. `relevance` to kolejność etapów wyszukiwania. "
                "Pozostałe porządkują **200 najlepszych trafień**, a nie cały "
                "zbi\u00f3r dopasowa\u0144: wyszukiwarka jest etapowa i nie zna go "
                "\u2014 dla prefiksu \u201ea\u201d jest ich 830 tys."
            ),
        ),
    ] = "relevance",
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
        q,
        entity_type=type,
        status=status,
        voivodeship=voivodeship,
        pkd=pkd,
        sort=sort,
        limit=limit,
        offset=offset,
        fuzzy=fuzzy,
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
                nip=h.nip,
                krs=h.krs,
                status=h.status,
                city=h.city,
                voivodeship=h.voivodeship,
                registered_on=h.registered_on,
                pkd=h.pkd,
            )
            for h in hits
        ],
    )
