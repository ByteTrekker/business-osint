"""Mapa zbiorcza — skupiska adresów zamiast pojedynczych znaczników.

Dwa punkty końcowe, bo mają różną częstotliwość: `/clusters` odpowiada na każde
przesunięcie widoku, `/coverage` opisuje zbiór danych i zmienia się wyłącznie
przy imporcie. Zliczenie adresów bez współrzędnych kosztuje 108 ms — doliczane
do każdego przesunięcia było najdroższą częścią odpowiedzi.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from business_osint.api.deps import SessionDep
from business_osint.repositories.map import MapRepository

router = APIRouter(prefix="/map", tags=["map"])

#: Największy dopuszczalny prostokąt w stopniach. Polska mieści się w około
#: 10 na 14 stopni, więc pytanie o więcej znaczy błąd po stronie klienta albo
#: próbę wyciągnięcia całej bazy jednym żądaniem.
MAX_ROZPIETOSC = 20.0


class ClusterOut(BaseModel):
    latitude: float
    longitude: float
    label: str | None = Field(
        default=None,
        description=(
            "Adres — tylko na poziomie szczegółowym. Gdy `addresses` jest "
            "większe od jedynki, jest to nazwa jednego z adresów pod tym "
            "punktem, nie ich wszystkich."
        ),
    )
    addresses: int = Field(description="Ile adresów wpadło do tej komórki")
    entities: int = Field(
        description=(
            "Przybliżona liczba podmiotów pod tymi adresami. Liczona ze stopnia "
            "węzła adresu, który zlicza wszystkie jego krawędzie — w praktyce "
            "niemal wyłącznie rejestracje, ale to przybliżenie, nie licznik."
        )
    )


class MapViewOut(BaseModel):
    clusters: list[ClusterOut]
    cell_degrees: float | None = Field(
        description="Bok komórki siatki. `null` znaczy, że to pojedyncze adresy."
    )
    truncated: bool = Field(description="Czy wynik przycięto limitem — patrz niezmiennik N3.")


class CoverageOut(BaseModel):
    """Czego na mapie nie widać. Bez tego pusty obszar jest nieodróżnialny od braku danych."""

    with_coordinates: int
    without_coordinates: int = Field(
        description="Adresy w bazie, których nie udało się dopasować do punktu PRG."
    )
    refreshed_at: dt.datetime | None = Field(
        description=(
            "Kiedy przeliczono siatkę skupisk. `null` znaczy, że nie przeliczono "
            "jej ani razu — mapa jest wtedy pusta nie dlatego, że nie ma firm."
        )
    )


@router.get("/clusters", response_model=MapViewOut, summary="Skupiska adresów w prostokącie")
async def get_clusters(
    session: SessionDep,
    south: Annotated[float, Query(ge=-90, le=90)],
    north: Annotated[float, Query(ge=-90, le=90)],
    west: Annotated[float, Query(ge=-180, le=180)],
    east: Annotated[float, Query(ge=-180, le=180)],
    zoom: Annotated[int, Query(ge=1, le=20)] = 7,
) -> MapViewOut:
    if north <= south or east <= west:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Pusty prostokąt")
    if north - south > MAX_ROZPIETOSC or east - west > MAX_ROZPIETOSC:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Prostokąt większy niż {MAX_ROZPIETOSC} stopni",
        )

    wycinek = await MapRepository(session).clusters(
        south=south, north=north, west=west, east=east, zoom=zoom
    )
    return MapViewOut(
        clusters=[
            ClusterOut(
                latitude=c.latitude,
                longitude=c.longitude,
                addresses=c.addresses,
                entities=c.entities,
                label=c.label,
            )
            for c in wycinek.clusters
        ],
        cell_degrees=wycinek.cell_degrees,
        truncated=wycinek.truncated,
    )


class AtPointOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    address: str
    nip: str | None = None
    krs: str | None = None
    status: str | None = None
    degree: int


class PointPageOut(BaseModel):
    items: list[AtPointOut]
    total: int
    has_more: bool


@router.get(
    "/point",
    response_model=PointPageOut,
    summary="Podmioty pod jednym punktem na mapie",
    description=(
        "Wszystkie podmioty zarejestrowane pod adresami o tych współrzędnych. "
        "To jest szersze pytanie niż `/entities/{id}/co-located`, które dotyczy "
        "jednego wpisu adresowego: w bloku każdy lokal jest osobnym adresem, "
        "a PRG daje im wszystkim jeden punkt budynku."
    ),
)
async def get_at_point(
    session: SessionDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PointPageOut:
    rows, total = await MapRepository(session).at_point(
        lat=lat, lon=lon, limit=limit, offset=offset
    )
    return PointPageOut(
        items=[
            AtPointOut(
                id=row["id"],
                type=row["entity_type"],
                name=row["display_name"],
                address=row["adres"],
                nip=row["nip"],
                krs=row["krs"],
                status=row["status"],
                degree=row["degree"],
            )
            for row in rows
        ],
        total=total,
        has_more=offset + len(rows) < total,
    )


@router.get("/coverage", response_model=CoverageOut, summary="Ile adresów nie trafia na mapę")
async def get_coverage(session: SessionDep) -> CoverageOut:
    pokrycie = await MapRepository(session).coverage()
    return CoverageOut(
        with_coordinates=pokrycie.with_coordinates,
        without_coordinates=pokrycie.without_coordinates,
        refreshed_at=pokrycie.refreshed_at,
    )
