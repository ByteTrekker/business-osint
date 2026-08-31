"""Import punktów adresowych PRG i dopasowanie ich do adresów w grafie.

Po co: żeby postawić firmy na mapie. Geokodowanie 2,4 mln adresów przez
Nominatim przy limicie jednego zapytania na sekundę to 28 dni odpytywania cudzej
infrastruktury; PRG daje te same współrzędne jednym pobraniem, bezpłatnie i do
dowolnego wykorzystania.

Import idzie **plik po pliku**, bo archiwum ma 32,4 GB po rozpakowaniu i nie ma
powodu trzymać go w całości na dysku. Każde województwo rozpakowujemy, wczytujemy
i kasujemy.

Dopasowanie jest **złączeniem po równości** na kluczu liczonym w Pythonie po obu
stronach. Odtworzenie normalizacji w SQL-u byłoby drugą implementacją tej samej
reguły — ta klasa błędu wystąpiła w tym projekcie już dwa razy i za każdym razem
kończyła się cichym rozjazdem danych.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.db.session import get_etl_sessionmaker
from business_osint.domain.normalization import address_point_key, wojewodztwo_z_teryt
from business_osint.etl.sources.prg import PunktAdresowy, czytaj_punkty

#: Wielkość partii przy `COPY`. Punktów jest około siedmiu milionów, więc
#: wstawianie po jednym oznaczałoby dobę zamiast minut.
BATCH_SIZE = 50_000

STAGE_COLUMNS = (
    "match_key",
    "city",
    "street",
    "building",
    "postal_code",
    "teryt",
    "simc",
    "ulic",
    "voivodeship",
    "latitude",
    "longitude",
)


@dataclass(slots=True)
class PrgStats:
    files: int = 0
    points_read: int = 0
    points_loaded: int = 0
    addresses_matched: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "files": self.files,
            "points_read": self.points_read,
            "points_loaded": self.points_loaded,
            "addresses_matched": self.addresses_matched,
        }


def wiersz(punkt: PunktAdresowy) -> tuple[Any, ...]:
    """Punkt na krotkę do ``COPY``, z kluczem dopasowania policzonym w Pythonie.

    Współrzędne idą jako `Decimal`, nie jako napis: `address_points` ma kolumny
    typu `numeric`, a `COPY` przez asyncpg nie konwertuje tekstu na liczbę —
    w odróżnieniu od tabeli pomocniczej CEIDG, gdzie wszystkie kolumny są
    tekstowe i napisy przechodzą.
    """
    return (
        address_point_key(city=punkt.city, street=punkt.street or "", building=punkt.building),
        punkt.city,
        punkt.street or "",
        punkt.building,
        punkt.postal_code or "",
        punkt.teryt or "",
        punkt.simc or "",
        punkt.ulic or "",
        wojewodztwo_z_teryt(punkt.teryt),
        Decimal(str(punkt.latitude)),
        Decimal(str(punkt.longitude)),
    )


async def wstaw_partie(session: AsyncSession, wiersze: Iterable[tuple[Any, ...]]) -> int:
    """Wrzuca partię przez ``COPY`` prosto do `address_points`."""
    batch = list(wiersze)
    if not batch:
        return 0
    raw = await session.connection()
    driver = (await raw.get_raw_connection()).driver_connection
    if driver is None:  # pragma: no cover - tylko przy egzotycznym dialekcie
        raise RuntimeError("COPY wymaga sterownika asyncpg")
    await driver.copy_records_to_table("address_points", records=batch, columns=list(STAGE_COLUMNS))
    return len(batch)


def rozpakuj_kolejno(archiwum: Path, katalog: Path) -> Iterator[Path]:
    """Rozpakowuje po jednym pliku GML i kasuje go po przetworzeniu.

    Całość zajmuje 32,4 GB. Trzymanie jej na dysku tylko po to, żeby przeczytać
    raz każdy plik, byłoby marnotrawstwem miejsca bez żadnej korzyści.
    """
    katalog.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archiwum) as zip_file:
        nazwy = sorted(n for n in zip_file.namelist() if n.lower().endswith(".gml"))
        for nazwa in nazwy:
            sciezka = katalog / Path(nazwa).name
            with zip_file.open(nazwa) as zrodlo, sciezka.open("wb") as cel:
                while fragment := zrodlo.read(8 * 1024 * 1024):
                    cel.write(fragment)
            try:
                yield sciezka
            finally:
                sciezka.unlink(missing_ok=True)


# Dopasowanie po kluczu. `DISTINCT ON` bierze jeden punkt na klucz: budynek
# z kilkoma wejściami ma w PRG kilka punktów oddalonych o metry, a do mapy
# potrzebny jest jeden.
#
# Uzupełniamy też TERYT, SIMC i ULIC — urzędowe identyfikatory administracyjne,
# których rejestry przedsiębiorców nie podają wcale, a które pozwalają łączyć
# adresy pewniej niż porównywanie napisów.
#
# Reguła rozstrzygająca: klucz niejednoznaczny **wymaga** zgodności województwa.
#
# Nazwa miejscowości nie identyfikuje miejsca — „Zawada", „Buczków" i „Lubień"
# istnieją w kilku województwach naraz. Dopasowanie po samej nazwie przypisało
# 7 459 adresom współrzędne oddalone o kilkaset kilometrów, i to z jednego
# tylko województwa wczytanego na próbę.
#
# Klucz występujący w całym kraju raz dopasowujemy bez tego warunku: brak
# województwa po naszej stronie (adresy z GLEIF i KRS go nie mają) nie jest
# sprzecznością, tylko niewiedzą, a jednoznaczny klucz i tak nie ma z czym
# się pomylić.
_MATCH = text("""
    WITH punkty AS (
        SELECT DISTINCT ON (match_key, voivodeship)
               match_key, voivodeship, latitude, longitude, teryt
        FROM address_points
        ORDER BY match_key, voivodeship, id
    ), jednoznaczne AS (
        SELECT match_key FROM punkty GROUP BY match_key HAVING count(*) = 1
    )
    UPDATE addresses a
    SET latitude = p.latitude,
        longitude = p.longitude,
        teryt = COALESCE(a.teryt, nullif(p.teryt, '')),
        geocoded_at = now()
    FROM punkty p
    WHERE a.match_key = p.match_key
      AND a.latitude IS NULL
      AND (
            a.voivodeship = p.voivodeship
            OR (a.voivodeship IS NULL AND p.match_key IN (SELECT match_key FROM jednoznaczne))
          )
""")

#: Klucz po naszej stronie liczymy raz, przy pierwszym dopasowaniu. Kolumna
#: istnieje od migracji 0007 i dotąd stoi pusta.
_ADDRESSES_WITHOUT_KEY = text("""
    SELECT entity_id, city, street, building
    FROM addresses
    WHERE match_key IS NULL AND city IS NOT NULL AND building IS NOT NULL
    ORDER BY entity_id
    LIMIT :batch_size OFFSET :offset
""")

_APPLY_KEYS = text("""
    UPDATE addresses a
    SET match_key = nowe.klucz
    FROM (SELECT unnest(CAST(:ids AS uuid[])) AS id,
                 unnest(CAST(:keys AS text[])) AS klucz) AS nowe
    WHERE a.entity_id = nowe.id
""")


async def policz_klucze(*, progress: Any = None) -> int:
    """Uzupełnia `addresses.match_key`. Zwraca liczbę opisanych adresów."""
    opisane = 0
    offset = 0
    factory = get_etl_sessionmaker()
    while True:
        async with factory() as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout = '30min'"))
            rows = (
                await session.execute(
                    _ADDRESSES_WITHOUT_KEY, {"batch_size": 20_000, "offset": offset}
                )
            ).all()
            if not rows:
                return opisane
            await session.execute(
                _APPLY_KEYS,
                {
                    "ids": [r.entity_id for r in rows],
                    "keys": [
                        address_point_key(
                            city=r.city or "", street=r.street or "", building=r.building or ""
                        )
                        for r in rows
                    ],
                },
            )
        opisane += len(rows)
        if progress is not None:
            progress(opisane)


async def import_prg(archiwum: Path, *, progress: Any = None) -> PrgStats:
    """Wczytuje punkty adresowe i dopasowuje je do adresów w bazie."""
    stats = PrgStats()
    factory = get_etl_sessionmaker()
    katalog = archiwum.parent / "_prg_rozpakowane"

    for plik in rozpakuj_kolejno(archiwum, katalog):
        partia: list[tuple[Any, ...]] = []
        async with factory() as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout = '60min'"))
            for punkt in czytaj_punkty(plik):
                stats.points_read += 1
                partia.append(wiersz(punkt))
                if len(partia) >= BATCH_SIZE:
                    stats.points_loaded += await wstaw_partie(session, partia)
                    partia.clear()
            stats.points_loaded += await wstaw_partie(session, partia)
        stats.files += 1
        if progress is not None:
            progress(stats, plik.name)

    await policz_klucze()

    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout = '60min'"))
        wynik = await session.execute(_MATCH)
        stats.addresses_matched = cast(CursorResult[Any], wynik).rowcount or 0
    return stats
