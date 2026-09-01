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
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.domain.map_grid import (
    LIMIT_KOMOREK,
    SIATKA,
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
    #: Wypełniana wyłącznie na poziomie szczegółowym. Gdy pod jednym punktem
    #: jest więcej adresów, jest to nazwa jednego z nich — liczba w `addresses`
    #: mówi, ilu dotyczy naprawdę.
    label: str | None = None


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

# Grupowanie po współrzędnych, nie po wierszu adresu. W bloku mieszkalnym każdy
# lokal jest osobnym adresem, a PRG daje im wszystkim jeden punkt budynku —
# znaczniki nakładały się co do piksela i klikalny był wyłącznie wierzchni.
# 209 836 punktów zbiera 678 217 adresów, więc pod cudzym znacznikiem znikało
# 468 381 adresów: ćwierć wszystkiego, co mapa w ogóle pokazuje. Najgorszy punkt
# ma 151 adresów.
#
# Bez `ORDER BY` po stopniu. Sortowanie malejąco po stopniu wyglądało
# niewinnie, a znaczyło: **przy przycięciu znikają najpierw najmniejsi**.
# Jednoosobowa działalność ma stopień 1, więc wypadała zawsze pierwsza —
# mapa po cichu ukrywała dokładnie tę część bazy, która stanowi jej większość.
# Kolejność jest teraz dowolna, bo przy przekroczeniu limitu i tak nie
# pokazujemy punktów, tylko wracamy do siatki (patrz `_punkty`).
#
# Poziom szczegółowy zwraca **identyfikator adresu**, bo dopiero tu znacznik
# odpowiada jednemu bytowi, o który da się dopytać. Klient używa go potem do
# `/entities/{id}/co-located` — nie dublujemy tu listy podmiotów, bo pod jednym
# adresem potrafi ich siedzieć 456 i ładowanie ich dla każdego widocznego
# znacznika byłoby setkami wierszy na zapas.
_PUNKTY = text("""
    SELECT a.latitude AS la, a.longitude AS lo,
           count(*) AS adresow,
           COALESCE(sum(e.degree), 0) AS podmiotow,
           min(e.display_name) AS etykieta
    FROM addresses a
    JOIN entities e ON e.id = a.entity_id AND e.merged_into_id IS NULL
    WHERE a.latitude IS NOT NULL
      AND a.latitude BETWEEN :south AND :north
      AND a.longitude BETWEEN :west AND :east
    GROUP BY a.latitude, a.longitude
    LIMIT :limit
""")

# Podmioty pod jednym punktem — czyli pod wszystkimi adresami o tych samych
# współrzędnych. `co-located` odpowiada na węższe pytanie: pod jednym **wpisem
# adresowym**. Dla bloku to jest różnica między „kto siedzi w tym mieszkaniu"
# a „kto siedzi w tym budynku", i mapa pyta o to drugie.
_POD_PUNKTEM = text("""
    SELECT e.id, e.entity_type, e.display_name, e.degree,
           c.nip, c.krs, c.status, adr.display_name AS adres
    FROM addresses a
    JOIN entities adr ON adr.id = a.entity_id AND adr.merged_into_id IS NULL
    JOIN relationships r ON r.target_entity_id = a.entity_id
                        AND r.relationship_type = 'registered_at'
                        AND r.superseded_at IS NULL
    JOIN entities e ON e.id = r.source_entity_id AND e.merged_into_id IS NULL
    LEFT JOIN companies c ON c.entity_id = e.id
    WHERE a.latitude = :lat AND a.longitude = :lon
    ORDER BY e.degree DESC, e.display_name
    LIMIT :limit OFFSET :offset
""")

_POD_PUNKTEM_ILE = text("""
    SELECT count(*)
    FROM addresses a
    JOIN relationships r ON r.target_entity_id = a.entity_id
                        AND r.relationship_type = 'registered_at'
                        AND r.superseded_at IS NULL
    JOIN entities e ON e.id = r.source_entity_id AND e.merged_into_id IS NULL
    WHERE a.latitude = :lat AND a.longitude = :lon
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
        """Pojedyncze adresy — o ile mieszczą się w limicie w całości.

        Jeżeli się nie mieszczą, **wracamy do siatki** zamiast obciąć listę.
        Obcięcie musiałoby coś porzucić, a każde kryterium wyboru jest tu
        kłamstwem o zawartości okna: sortowanie po stopniu ukrywało jednoosobowe
        działalności, a losowe obcięcie ukrywałoby je równie skutecznie, tylko
        mniej przewidywalnie. Siatka nie gubi nikogo — każdy adres jest w jakiejś
        komórce policzony — a `cell_degrees` mówi klientowi, który tryb dostał.
        """
        params: dict[str, Any] = {
            "south": south,
            "north": north,
            "west": west,
            "east": east,
            # O jeden więcej, niż wolno pokazać: inaczej nie da się odróżnić
            # „dokładnie tyle" od „więcej, niż się zmieści".
            "limit": LIMIT_KOMOREK + 1,
        }
        rows = (await self._session.execute(_PUNKTY, params)).mappings().all()
        if len(rows) > LIMIT_KOMOREK:
            return await self._skupiska(
                south=south, north=north, west=west, east=east, zoom=max(SIATKA)
            )
        return WycinekMapy(
            clusters=[self._skupisko(row) for row in rows],
            cell_degrees=None,
            truncated=False,
        )

    @staticmethod
    def _skupisko(row: Any) -> Skupisko:
        return Skupisko(
            latitude=float(row["la"]),
            longitude=float(row["lo"]),
            addresses=int(row["adresow"]),
            entities=int(row["podmiotow"]),
            label=row.get("etykieta"),
        )

    async def at_point(
        self, *, lat: float, lon: float, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Podmioty pod wszystkimi adresami o tych współrzędnych.

        Współrzędne idą jako `Decimal`, nie jako `float`. Kolumny są typu
        `numeric(9,6)`, a asyncpg zakodowałby liczbę zmiennoprzecinkową w jej
        pełnym rozwinięciu binarnym: `54.37967199999999…` nie równa się
        `54.379672` i zapytanie zwraca **zero wierszy bez żadnego błędu**.
        Ta sama pułapka co przy `COPY` w imporcie PRG.
        """
        params: dict[str, Any] = {"lat": Decimal(str(lat)), "lon": Decimal(str(lon))}
        ile = int((await self._session.execute(_POD_PUNKTEM_ILE, params)).scalar_one())
        rows = (
            await self._session.execute(_POD_PUNKTEM, {**params, "limit": limit, "offset": offset})
        ).mappings()
        return [dict(row) for row in rows], ile

    async def coverage(self) -> Pokrycie:
        """Metadane zbioru — nie na ścieżce przesuwania mapy, patrz `api/v1/map`."""
        row = (await self._session.execute(_POKRYCIE)).mappings().one()
        przeliczono = row["przeliczono"]
        return Pokrycie(
            with_coordinates=int(row["z_wspolrzednymi"]),
            without_coordinates=int(row["bez_wspolrzednych"]),
            refreshed_at=przeliczono if isinstance(przeliczono, dt.datetime) else None,
        )
