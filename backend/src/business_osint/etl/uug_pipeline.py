"""Geokodowanie adresów, których dopasowanie do PRG nie objęło.

Import PRG dopasowuje adresy **po znormalizowanym kluczu** — miejscowość, ulica,
numer sprowadzone do wspólnej postaci. To działa dla 1,95 mln adresów i zawodzi
dla 475 707: rejestr przedsiębiorców zapisał ulicę inaczej niż PRG, numer ma
postać, której normalizacja nie przewidziała, albo miejscowości nie ma w kluczu.

UUG odpytuje te same dane **po adresie**, więc radzi sobie tam, gdzie porównanie
napisów nie dało rady. Cena: jedno zapytanie na adres zamiast jednego złączenia
na całość.

Reguła bezpieczeństwa, przeniesiona wprost z importu PRG: **geokoder może
odpowiedzieć o innym miejscu, niż pytaliśmy**. „Zawada" istnieje w kilku
województwach i usługa zwróci którąś. Dlatego porównujemy TERYT odpowiedzi
z województwem, które już znamy, i przy niezgodzie **odrzucamy punkt**.
Dopasowanie po samej nazwie przypisało kiedyś 7 459 adresom współrzędne
oddalone o setki kilometrów.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from business_osint.db.session import get_etl_sessionmaker
from business_osint.domain.enums import SourceKind
from business_osint.domain.normalization import wojewodztwo_z_teryt
from business_osint.etl.fetching.profiles import PROFILES
from business_osint.etl.sources.uug import UugClient

#: Po tylu nieudanych adresach z rzędu przerywamy przebieg.
MAX_KOLEJNYCH_BLEDOW = 20

#: Ile adresów pytamy równolegle — **z profilu źródła**, nie ze stałej w tym
#: pliku. Reguła „przy zapytaniach per podmiot współbieżność wynosi jeden" ma
#: test w `tests/unit/test_fetching.py`, ale test sprawdza profil. Gdyby
#: pipeline trzymał własną liczbę, reguła obowiązywałaby w konfiguracji
#: i była łamana w kodzie — czyli nie obowiązywałaby wcale.
ROWNOLEGLE = PROFILES[SourceKind.GUGIK].concurrency


@dataclass(slots=True)
class UugStats:
    checked: int = 0
    located: int = 0
    not_found: int = 0
    rejected_voivodeship: int = 0
    errors: int = 0
    last_id: str = ""
    aborted: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "located": self.located,
            "not_found": self.not_found,
            "rejected_voivodeship": self.rejected_voivodeship,
            "errors": self.errors,
            "last_id": self.last_id,
            "aborted": self.aborted,
        }


_DO_GEOKODOWANIA = text("""
    SELECT entity_id, city, street, building, voivodeship
    FROM addresses
    WHERE latitude IS NULL
      AND city IS NOT NULL AND building IS NOT NULL
      AND (CAST(:after AS uuid) IS NULL OR entity_id > CAST(:after AS uuid))
    ORDER BY entity_id
    LIMIT CAST(:limit AS bigint)
""")

_ZAPISZ = text("""
    UPDATE addresses
    SET latitude = :lat, longitude = :lon,
        teryt = COALESCE(teryt, nullif(:teryt, '')),
        simc = COALESCE(simc, nullif(:simc, '')),
        ulic = COALESCE(ulic, nullif(:ulic, '')),
        geocoded_at = now()
    WHERE entity_id = :id AND latitude IS NULL
""")


async def geocode_missing(
    *, limit: int | None = None, after: str | None = None, progress: Any = None
) -> UugStats:
    """Uzupełnia współrzędne przez UUG. `after` wznawia przebieg."""
    import asyncio

    stats = UugStats()
    factory = get_etl_sessionmaker()
    async with factory() as session:
        cele = (await session.execute(_DO_GEOKODOWANIA, {"limit": limit, "after": after})).all()
    if not cele:
        return stats

    client = UugClient()
    pod_rzad = 0
    try:
        for start in range(0, len(cele), ROWNOLEGLE):
            paczka = cele[start : start + ROWNOLEGLE]
            wyniki = await asyncio.gather(
                *(client.locate(c.city, c.street, c.building) for c in paczka),
                return_exceptions=True,
            )

            przerwij = False
            do_zapisu = []
            for cel, wynik in zip(paczka, wyniki, strict=True):
                if isinstance(wynik, BaseException):
                    stats.errors += 1
                    pod_rzad += 1
                    if pod_rzad >= MAX_KOLEJNYCH_BLEDOW:
                        stats.aborted = f"{MAX_KOLEJNYCH_BLEDOW} błędów z rzędu: {wynik}"
                        przerwij = True
                        break
                    continue
                pod_rzad = 0
                stats.checked += 1

                if wynik is None:
                    stats.not_found += 1
                    continue
                # Punkt z innego województwa niż to, które już znamy, jest
                # odpowiedzią o innym miejscu — odrzucamy zamiast zapisać.
                z_teryt = wojewodztwo_z_teryt(wynik.teryt)
                if cel.voivodeship and z_teryt and z_teryt != cel.voivodeship:
                    stats.rejected_voivodeship += 1
                    continue
                do_zapisu.append((cel, wynik))

            if do_zapisu:
                async with factory() as session, session.begin():
                    for cel, punkt in do_zapisu:
                        await session.execute(
                            _ZAPISZ,
                            {
                                "id": cel.entity_id,
                                "lat": punkt.latitude,
                                "lon": punkt.longitude,
                                "teryt": punkt.teryt or "",
                                "simc": punkt.simc or "",
                                "ulic": punkt.ulic or "",
                            },
                        )
                        stats.located += 1

            if przerwij:
                break
            stats.last_id = str(paczka[-1].entity_id)
            if progress is not None:
                progress(stats)
    finally:
        await client.aclose()
    return stats
