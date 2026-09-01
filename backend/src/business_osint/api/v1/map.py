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
    address_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Identyfikator adresu — wypełniony wyłącznie na poziomie "
            "szczegółowym. Podaj go do `/entities/{id}/co-located`, żeby "
            "dostać podmioty zarejestrowane pod tym adresem."
        ),
    )
    label: str | None = Field(default=None, description="Adres, jeśli znacznik jest pojedynczy")
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
                address_id=c.address_id,
                label=c.label,
            )
            for c in wycinek.clusters
        ],
        cell_degrees=wycinek.cell_degrees,
        truncated=wycinek.truncated,
    )


@router.get("/coverage", response_model=CoverageOut, summary="Ile adresów nie trafia na mapę")
async def get_coverage(session: SessionDep) -> CoverageOut:
    pokrycie = await MapRepository(session).coverage()
    return CoverageOut(
        with_coordinates=pokrycie.with_coordinates,
        without_coordinates=pokrycie.without_coordinates,
        refreshed_at=pokrycie.refreshed_at,
    )
