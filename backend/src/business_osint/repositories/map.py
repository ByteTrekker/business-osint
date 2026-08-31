"""Agregacja adresów do siatki — pod mapę zbiorczą.

Dwa i pół miliona znaczników nie ma prawa trafić do przeglądarki. Biblioteki
klastrujące po stronie klienta dostają pełną listę punktów i grupują ją lokalnie;
przy tej skali przeglądarka umrze, zanim cokolwiek narysuje.

Dlatego grupowanie dzieje się w bazie: zwracamy **liczności komórek siatki**,
a nie punkty. Rozmiar komórki zależy od przybliżenia, więc odpowiedź ma zawsze
podobną wielkość niezależnie od tego, czy ktoś ogląda cały kraj, czy jedną ulicę.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.domain.map_grid import (
    LIMIT_KOMOREK,
    SIATKA_BAZOWA,
    SZCZEGOL_OD,
    bok_komorki,
    zwielokrotnienie,
)


@dataclass(slots=True)
class Skupisko:
    latitude: float
    longitude: float
    addresses: int
    entities: int


@dataclass(slots=True)
class WycinekMapy:
    clusters: list[Skupisko]
    cell_degrees: float | None
    truncated: bool


# Zwijanie siatki bazowej. `floor` po indeksach całkowitych jest dokładne:
# `floor(floor(x/f)/k)` równa się `floor(x/(f*k))` dla całkowitego `k` — przy
# `round` ta równość nie zachodzi i poziomy rozjeżdżałyby się o pół komórki.
#
# Znacznik stawiamy w **środku masy** komórki (`sum/count`), nie w jej rogu:
# sumy współrzędnych są addytywne, więc zwijają się razem z licznikami, a
# skupisko ląduje tam, gdzie faktycznie stoją adresy.
#
# `sum(entities)` to przybliżenie liczby podmiotów pod adresem, nie dokładny
# licznik: stopień węzła adresu liczy wszystkie jego krawędzie. W praktyce
# adres ma niemal wyłącznie krawędzie `registered_at`, więc różnica jest
# marginalna — ale nazywamy to „podmiotami", nie „firmami", żeby nie obiecywać
# precyzji, której tu nie ma.
_SKUPISKA = text("""
    SELECT sum(lat_sum) / sum(addresses) AS la,
           sum(lon_sum) / sum(addresses) AS lo,
           sum(addresses) AS adresow,
           sum(entities) AS podmiotow
    FROM address_cells
    WHERE lat_idx BETWEEN :lat_od AND :lat_do
      AND lon_idx BETWEEN :lon_od AND :lon_do
    GROUP BY floor(lat_idx::numeric / :k), floor(lon_idx::numeric / :k)
    ORDER BY adresow DESC
    LIMIT :limit
""")

_PUNKTY = text("""
    SELECT a.latitude AS la, a.longitude AS lo, 1 AS adresow, e.degree AS podmiotow
    FROM addresses a
    JOIN entities e ON e.id = a.entity_id AND e.merged_into_id IS NULL
    WHERE a.latitude IS NOT NULL
      AND a.latitude BETWEEN :south AND :north
      AND a.longitude BETWEEN :west AND :east
    ORDER BY e.degree DESC
    LIMIT :limit
""")


@dataclass(slots=True)
class Pokrycie:
    """Ile z bazy widać na mapie, a ile nie."""

    with_coordinates: int
    without_coordinates: int
    #: Kiedy przeliczono siatkę. `None` znaczy, że nie przeliczono jej nigdy —
    #: mapa jest wtedy pusta nie dlatego, że nie ma danych, tylko dlatego, że
    #: nikt nie uruchomił `odswiez_siatke_adresow()`. Pusta mapa bez tej
    #: informacji wygląda identycznie jak brak firm w kraju.
    refreshed_at: dt.datetime | None


# Liczone jednym przebiegiem po `addresses`, nie dwoma zapytaniami: to i tak
# jest skan całej tabeli, a dwa skany zamiast jednego niczego nie wyjaśniają.
_POKRYCIE = text("""
    SELECT count(*) FILTER (WHERE latitude IS NOT NULL) AS z_wspolrzednymi,
           count(*) FILTER (WHERE latitude IS NULL) AS bez_wspolrzednych,
           (SELECT max(refreshed_at) FROM address_cells) AS przeliczono
    FROM addresses
""")


class MapRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def clusters(
        self, *, south: float, north: float, west: float, east: float, zoom: int
    ) -> WycinekMapy:
        """Skupiska w podanym prostokącie, zgrubne albo szczegółowe wedle przybliżenia."""
        if zoom >= SZCZEGOL_OD:
            return await self._punkty(south=south, north=north, west=west, east=east)
        return await self._skupiska(south=south, north=north, west=west, east=east, zoom=zoom)

    async def _skupiska(
        self, *, south: float, north: float, west: float, east: float, zoom: int
    ) -> WycinekMapy:
        cell = bok_komorki(zoom)
        baza = float(SIATKA_BAZOWA)
        rows = (
            (
                await self._session.execute(
                    _SKUPISKA,
                    {
                        # Granice prostokąta na indeksy komórek bazowych.
                        # Zaokrąglamy na zewnątrz, żeby komórka przecięta
                        # krawędzią widoku nie wypadła z wyniku.
                        "lat_od": math.floor(south / baza),
                        "lat_do": math.floor(north / baza),
                        "lon_od": math.floor(west / baza),
                        "lon_do": math.floor(east / baza),
                        "k": zwielokrotnienie(cell),
                        "limit": LIMIT_KOMOREK,
                    },
                )
            )
            .mappings()
            .all()
        )
        return WycinekMapy(
            clusters=[self._skupisko(row) for row in rows],
            cell_degrees=float(cell),
            truncated=len(rows) >= LIMIT_KOMOREK,
        )

    async def _punkty(self, *, south: float, north: float, west: float, east: float) -> WycinekMapy:
        params: dict[str, Any] = {
            "south": south,
            "north": north,
            "west": west,
            "east": east,
            "limit": LIMIT_KOMOREK,
        }
        rows = (await self._session.execute(_PUNKTY, params)).mappings().all()
        return WycinekMapy(
            clusters=[self._skupisko(row) for row in rows],
            cell_degrees=None,
            truncated=len(rows) >= LIMIT_KOMOREK,
        )

    @staticmethod
    def _skupisko(row: Any) -> Skupisko:
        return Skupisko(
            latitude=float(row["la"]),
            longitude=float(row["lo"]),
            addresses=int(row["adresow"]),
            entities=int(row["podmiotow"]),
        )

    async def coverage(self) -> Pokrycie:
        """Metadane zbioru — nie na ścieżce przesuwania mapy, patrz `api/v1/map`."""
        row = (await self._session.execute(_POKRYCIE)).mappings().one()
        przeliczono = row["przeliczono"]
        return Pokrycie(
            with_coordinates=int(row["z_wspolrzednymi"]),
            without_coordinates=int(row["bez_wspolrzednych"]),
            refreshed_at=przeliczono if isinstance(przeliczono, dt.datetime) else None,
        )
