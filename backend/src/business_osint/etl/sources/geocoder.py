"""Geokodowanie adresów przez Nominatim (OpenStreetMap).

Nominatim jest bezpłatny, ale jego regulamin dopuszcza **jedno zapytanie na
sekundę** i wymaga identyfikującego się nagłówka ``User-Agent``. Dlatego adres
geokodujemy **raz w życiu** i zapisujemy współrzędne w bazie — geokodowanie przy
każdym wyświetleniu profilu byłoby nadużyciem cudzej infrastruktury, a przy
2,4 mln adresów po prostu niewykonalne.

Wynik jest przybliżony: mamy ulicę, numer i miejscowość, więc trafiamy w budynek
albo w ulicę. To wystarcza, żeby pokazać, gdzie podmiot siedzi — nie do nawigacji.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from business_osint.etl.fetching.client import ResilientClient
from business_osint.etl.fetching.errors import FetchError
from business_osint.etl.fetching.policy import RetryPolicy
from business_osint.etl.fetching.rate_limit import RateLimiter

BASE_URL = "https://nominatim.openstreetmap.org/search"

#: Nominatim nie rozpoznaje polskich skrótów rodzaju ulicy — „ul. Kąty" nie
#: znajduje niczego, samo „Kąty" trafia. Rejestry zapisują je niekonsekwentnie,
#: więc usuwamy je przed zapytaniem.
_STREET_PREFIX = re.compile(
    r"^(ul\.|ul\b|al\.|al\b|aleja|aleje|pl\.|plac|os\.|osiedle|rondo|skwer)\s+",
    re.IGNORECASE,
)


def strip_street_prefix(street: str | None) -> str | None:
    """Usuwa skrót rodzaju ulicy z początku nazwy."""
    if not street:
        return street
    return _STREET_PREFIX.sub("", street.strip()).strip() or None


#: Regulamin Nominatim: maksymalnie jedno zapytanie na sekundę.
MAX_RATE = 1.0
USER_AGENT = "business-osint/0.1 (+https://github.com/ByteTrekker/business-osint)"


@dataclass(frozen=True, slots=True)
class Coordinates:
    latitude: float
    longitude: float


class Geocoder:
    def __init__(self, client: ResilientClient | None = None) -> None:
        self._client = client or ResilientClient(
            source="nominatim",
            client=httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            ),
            rate_limiter=RateLimiter(MAX_RATE),
            retry_policy=RetryPolicy(max_attempts=3, initial_backoff=2.0),
        )

    async def locate(
        self, *, street: str | None, building: str | None, postal_code: str | None, city: str | None
    ) -> Coordinates | None:
        """Współrzędne adresu albo ``None``, gdy nie udało się go odnaleźć.

        Brak wyniku jest normalnym stanem — część adresów z rejestru nie istnieje
        w OSM albo jest zapisana w postaci, której geokoder nie rozpozna.
        """
        query = ", ".join(
            part
            for part in (
                " ".join(p for p in (strip_street_prefix(street), building) if p),
                postal_code,
                city,
                "Polska",
            )
            if part
        )
        if not query.strip(", "):
            return None

        try:
            document = await self._client.get_json(
                BASE_URL,
                external_id=query[:120],
                params={"q": query, "format": "json", "limit": 1, "countrycodes": "pl"},
            )
        except FetchError:
            return None

        items = document.payload.get("items") or []
        if not items:
            return None
        first = items[0]
        try:
            return Coordinates(float(first["lat"]), float(first["lon"]))
        except (KeyError, TypeError, ValueError):
            return None

    async def aclose(self) -> None:
        await self._client.aclose()
