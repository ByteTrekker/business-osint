"""Biuletyn Zamówień Publicznych (e-Zamowienia).

Publiczne API bez klucza. Wartość dla grafu: ogłoszenie o wyniku wiąże
**zamawiającego** z **wykonawcą**, obu z numerem NIP — czyli daje krawędź
między podmiotem publicznym a firmą, której nie ma w żadnym rejestrze
spółek.

Źródło jest naturalnie przyrostowe: sortujemy malejąco po dacie publikacji
i schodzimy tylko do daty, którą już mamy.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator

import httpx

from business_osint.domain.enums import SourceKind
from business_osint.etl.fetching.client import FetchedDocument, ResilientClient
from business_osint.etl.fetching.policy import RetryPolicy
from business_osint.etl.fetching.rate_limit import RateLimiter

BASE_URL = "https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search"

#: API zwraca najwyżej kilkanaście rekordów na stronę niezależnie od PageSize.
PAGE_SIZE = 60
DEFAULT_RATE = 2.0

USER_AGENT = "business-osint/0.1 (+https://github.com/ByteTrekker/business-osint)"


class BzpClient:
    def __init__(self, client: ResilientClient | None = None) -> None:
        self._client = client or self._build_default()

    @staticmethod
    def _build_default() -> ResilientClient:
        return ResilientClient(
            source=SourceKind.BZP.value,
            client=httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            ),
            rate_limiter=RateLimiter(DEFAULT_RATE),
            retry_policy=RetryPolicy(max_attempts=4, initial_backoff=2.0),
        )

    async def iter_notices(
        self, *, days_back: int = 30, until: dt.date | None = None
    ) -> AsyncIterator[FetchedDocument]:
        """Ogłoszenia dzień po dniu, od najnowszych.

        Parametr ``Page`` jest przez API **ignorowany** — strona 1, 3 i 7 zwracają
        identyczny zestaw. Jedyne działające zawężenie to zakres dat, przy twardym
        limicie ok. 10 rekordów na wywołanie. To źródło nadaje się więc do
        codziennego dociągania nowości, a nie do zbudowania historii wstecz.
        """
        end = until or dt.date.today()
        for offset in range(days_back):
            day = end - dt.timedelta(days=offset)
            document = await self._client.get_json(
                BASE_URL,
                external_id=f"bzp/{day.isoformat()}",
                params={
                    "PageSize": PAGE_SIZE,
                    "PublicationDateFrom": day.isoformat(),
                    "PublicationDateTo": (day + dt.timedelta(days=1)).isoformat(),
                    "SortingColumnName": "PublicationDate",
                    "SortingDirection": "DESC",
                },
            )
            if document.payload.get("items"):
                yield document

    @property
    def stats(self) -> dict[str, int]:
        return self._client.stats.as_dict()

    async def aclose(self) -> None:
        await self._client.aclose()
