"""Uniwersalna Usługa Geokodowania GUGiK.

Rządowy geokoder oparty o Państwowy Rejestr Granic — te same dane, co import
PRG, ale odpytywane po adresie zamiast dopasowywane po znormalizowanym kluczu.
Dlatego trafia tam, gdzie dopasowanie zawiodło: 475 707 adresów nie znalazło
swojego punktu, bo napis nie pasował znak w znak.

Wybór między nim a Nominatimem nie jest kwestią gustu. Nominatim dopuszcza
jedno zapytanie na sekundę i interpoluje położenie wzdłuż ulicy; UUG odpowiada
ponad dwa razy szybciej, wskazuje **punkt adresowy budynku** i przy okazji
zwraca TERYT, SIMC i ULIC — urzędowe identyfikatory, których żaden rejestr
przedsiębiorców nie podaje.

**Kolejność osi jest sprawdzona pomiarem.** Usługa zwraca `x` i `y` w układzie
PUWG 1992 (EPSG:2180). Dla ul. Gustawa Morcinka w Warszawie odczyt `x` jako
easting daje 52,26 N i 20,92 E — czyli Warszawę. Odwrotny daje 53,54 N i 18,85 E,
punkt oddalony o ponad dwieście kilometrów. Błąd tej klasy przechodzi przez
każdy test sprawdzający tylko, czy punkt leży „gdzieś w Polsce".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from pyproj import Transformer

from business_osint.domain.enums import SourceKind
from business_osint.etl.fetching.client import ResilientClient
from business_osint.etl.fetching.errors import FetchError
from business_osint.etl.fetching.policy import RetryPolicy
from business_osint.etl.fetching.rate_limit import RateLimiter

BASE_URL = "https://services.gugik.gov.pl/uug/"

#: Usługa nie publikuje limitu w nagłówkach ani w regulaminie. Zmierzone tempo
#: sekwencyjne to 2,1 zapytania na sekundę i ogranicza je opóźnienie sieci,
#: nie serwer. Zostajemy poniżej tego, co i tak osiągalne — cudza infrastruktura
#: bez podanego limitu to nie jest zaproszenie do dociskania.
DEFAULT_RATE = 4.0

USER_AGENT = "business-osint/0.1 (+https://github.com/ByteTrekker/business-osint)"

#: `always_xy` mówi pyprojowi, żeby przyjmował (easting, northing) niezależnie
#: od urzędowej kolejności osi układu — a UUG właśnie tak zwraca współrzędne.
_TRANSFORMER = Transformer.from_crs(2180, 4326, always_xy=True)


@dataclass(frozen=True, slots=True)
class Punkt:
    latitude: float
    longitude: float
    teryt: str | None
    simc: str | None
    ulic: str | None
    #: Nazwa dopasowana przez usługę — bywa inna niż nasza. Trzymamy ją,
    #: bo różnica jest jedynym sygnałem, że geokoder trafił gdzie indziej.
    dopasowany: str


def zapytanie(city: str, street: str | None, building: str) -> str:
    """Adres w postaci, którą usługa rozumie.

    Przecinek po miejscowości jest **obowiązkowy** — bez niego usługa nie trafia.
    """
    ulica = (street or "").strip()
    return f"{city.strip()}, {ulica} {building.strip()}".replace("  ", " ").strip()


def punkt_z_odpowiedzi(payload: dict[str, Any]) -> Punkt | None:
    """Pierwszy wynik przeliczony na WGS84 albo ``None``."""
    wyniki = payload.get("results") or {}
    pierwszy = wyniki.get("1")
    if not isinstance(pierwszy, dict):
        return None
    try:
        easting = float(pierwszy["x"])
        northing = float(pierwszy["y"])
    except (KeyError, TypeError, ValueError):
        return None
    lon, lat = _TRANSFORMER.transform(easting, northing)
    return Punkt(
        latitude=round(lat, 6),
        longitude=round(lon, 6),
        teryt=str(pierwszy.get("teryt") or "") or None,
        simc=str(pierwszy.get("simc") or "") or None,
        ulic=str(pierwszy.get("ulic") or "") or None,
        dopasowany=" ".join(
            str(pierwszy.get(k) or "") for k in ("city", "street", "number")
        ).strip(),
    )


class UugClient:
    def __init__(self, client: ResilientClient | None = None) -> None:
        self._client = client or ResilientClient(
            source=SourceKind.GUGIK.value,
            client=httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            ),
            rate_limiter=RateLimiter(DEFAULT_RATE),
            retry_policy=RetryPolicy(max_attempts=3, initial_backoff=2.0),
        )

    async def locate(self, city: str, street: str | None, building: str) -> Punkt | None:
        adres = zapytanie(city, street, building)
        try:
            document = await self._client.get_json(
                BASE_URL,
                external_id=f"uug/{adres}",
                params={"request": "GetAddress", "address": adres},
            )
        except FetchError:
            raise
        return punkt_z_odpowiedzi(document.payload)

    async def aclose(self) -> None:
        await self._client.aclose()
