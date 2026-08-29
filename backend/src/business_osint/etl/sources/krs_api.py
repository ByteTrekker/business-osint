"""Klient API Ministerstwa Sprawiedliwości (KRS).

Warstwa odporności (tempo, ponawianie, bezpiecznik) siedzi w
``etl.fetching.client`` — tutaj zostaje wyłącznie wiedza o samym rejestrze:
adresy, rodzaje odpisów i znaczenie parametrów.

Endpointy (do potwierdzenia na żywym odpisie przed produkcją):

* ``GET {BASE}/OdpisAktualny/{krs}?rejestr=P&format=json``
* ``GET {BASE}/OdpisPelny/{krs}?rejestr=P&format=json``

Odpis **pełny** zawiera wpisy wykreślone i tylko on daje historię powiązań
(„był członkiem zarządu 2020–2023”). Aktualny służy do codziennego odświeżania.
"""

from __future__ import annotations

import httpx

from business_osint.domain.enums import SourceKind
from business_osint.etl.fetching.client import FetchedDocument, ResilientClient
from business_osint.etl.fetching.profiles import profile_for
from business_osint.etl.fetching.rate_limit import RateLimiter

BASE_URL = "https://api-krs.ms.gov.pl/api/krs"
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

#: Rejestr przedsiębiorców i rejestr stowarzyszeń — inne zestawy pól.
REGISTRY_BUSINESS = "P"
REGISTRY_ASSOCIATION = "S"

#: Kontakt w User-Agent: obciążamy cudzą infrastrukturę, więc dajemy się namierzyć.
USER_AGENT = "business-osint/0.1 (+https://github.com/ByteTrekker/business-osint)"


class KrsClient:
    """Pobiera odpisy KRS. Nie wypuszcza wyjątków httpx — tylko ``FetchError``."""

    def __init__(self, client: ResilientClient | None = None) -> None:
        self._client = client or self._build_default()

    @staticmethod
    def _build_default() -> ResilientClient:
        profile = profile_for(SourceKind.KRS)
        return ResilientClient(
            source=profile.name,
            client=httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            ),
            rate_limiter=RateLimiter(profile.rate_per_second),
            retry_policy=profile.retry,
        )

    async def fetch_full(self, krs: str, *, registry: str = REGISTRY_BUSINESS) -> FetchedDocument:
        """Odpis pełny — z wpisami wykreślonymi, czyli z historią."""
        return await self._fetch("OdpisPelny", krs, registry)

    async def fetch_current(
        self, krs: str, *, registry: str = REGISTRY_BUSINESS
    ) -> FetchedDocument:
        """Odpis aktualny — tańszy, do codziennego odświeżania."""
        return await self._fetch("OdpisAktualny", krs, registry)

    async def _fetch(self, kind: str, krs: str, registry: str) -> FetchedDocument:
        return await self._client.get_json(
            f"{BASE_URL}/{kind}/{krs}",
            external_id=krs,
            params={"rejestr": registry, "format": "json"},
        )

    @property
    def stats(self) -> dict[str, int]:
        return self._client.stats.as_dict()

    async def aclose(self) -> None:
        await self._client.aclose()
