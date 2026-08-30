"""Klient GLEIF — globalnego rejestru identyfikatorów podmiotów prawnych (LEI).

Dlaczego to źródło jest pierwsze:

* **Licencja CC0** — użycie komercyjne, redystrybucja i produkty pochodne bez
  ograniczeń i bez wymogu atrybucji. Żadnej niejasności prawnej, w odróżnieniu
  od masowego pobierania z KRS (art. 60a ustawy o KRS).
* **Gotowe krawędzie właścicielskie** (poziom 2): podmiot -> spółka dominująca
  bezpośrednia i ostateczna. To jedyne otwarte źródło struktur właścicielskich,
  w dodatku transgranicznych.
* **Krajowy identyfikator** w polu ``registeredAs`` pozwala spiąć rekord LEI
  z podmiotem, który mamy już z REGON albo KRS.

Ograniczenie, o którym trzeba pamiętać: LEI mają wyłącznie podmioty, które go
potrzebowały (rynki finansowe, emitenci, duże grupy). W Polsce to ok. 43 tys.
podmiotów, a nie cały rejestr — GLEIF uzupełnia obraz, nie zastępuje go.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from business_osint.domain.enums import SourceKind
from business_osint.etl.fetching.client import FetchedDocument, ResilientClient
from business_osint.etl.fetching.errors import NotFoundError
from business_osint.etl.fetching.policy import RetryPolicy
from business_osint.etl.fetching.rate_limit import RateLimiter

BASE_URL = "https://api.gleif.org/api/v1"
GOLDEN_COPY_URL = "https://goldencopy.gleif.org/api/v2/golden-copies/publishes"

#: GLEIF nie publikuje twardego limitu; trzymamy się umiarkowanego tempa.
DEFAULT_RATE = 5.0
MAX_PAGE_SIZE = 200

USER_AGENT = "business-osint/0.1 (+https://github.com/ByteTrekker/business-osint)"


class GleifClient:
    """Czyta rekordy LEI i relacje właścicielskie."""

    def __init__(self, client: ResilientClient | None = None) -> None:
        self._client = client or self._build_default()

    @staticmethod
    def _build_default() -> ResilientClient:
        return ResilientClient(
            source=SourceKind.GLEIF.value,
            client=httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.api+json"},
                follow_redirects=True,
            ),
            rate_limiter=RateLimiter(DEFAULT_RATE, burst=3),
            retry_policy=RetryPolicy(max_attempts=4, initial_backoff=2.0),
        )

    async def iter_lei_records(
        self, *, country: str = "PL", page_size: int = MAX_PAGE_SIZE, max_pages: int | None = None
    ) -> AsyncIterator[FetchedDocument]:
        """Strony rekordów LEI dla danego kraju.

        Stronicowanie kursorem, nie numerem strony: GLEIF odrzuca zapytania,
        w których ``page[number] * page[size]`` przekracza 10 000, a polskich
        podmiotów jest ponad 42 tys. Kursor nie ma tego ograniczenia i jest
        odporny na zmiany danych w trakcie przebiegu.
        """
        cursor = "*"
        page = 0
        while max_pages is None or page < max_pages:
            document = await self._client.get_json(
                f"{BASE_URL}/lei-records",
                external_id=f"lei-records/{country}/cursor-{page}",
                params={
                    "filter[entity.legalAddress.country]": country,
                    "page[size]": page_size,
                    "page[cursor]": cursor,
                },
            )
            records = document.payload.get("data") or []
            if not records:
                return
            yield document
            page += 1

            next_link = ((document.payload.get("links") or {}).get("next")) or ""
            next_cursor = _cursor_from_link(next_link)
            if not next_cursor or next_cursor == cursor:
                return
            cursor = next_cursor

    async def fetch_by_leis(self, leis: list[str]) -> AsyncIterator[FetchedDocument]:
        """Pobiera konkretne rekordy LEI po identyfikatorze.

        Używane do domykania grafu: relacje właścicielskie wskazują na spółki
        matki, które często są zagraniczne, więc nie ma ich w imporcie krajowym.
        Bez nich krawędź nie ma drugiego końca i przepada.
        """
        for start in range(0, len(leis), MAX_PAGE_SIZE):
            batch = leis[start : start + MAX_PAGE_SIZE]
            yield await self._client.get_json(
                f"{BASE_URL}/lei-records",
                external_id=f"lei-records/by-id/{start}",
                params={"filter[lei]": ",".join(batch), "page[size]": MAX_PAGE_SIZE},
            )

    async def fetch_parent(self, lei: str, *, ultimate: bool = False) -> dict[str, Any] | None:
        """Spółka dominująca. ``None`` znaczy „brak relacji", nie „błąd"."""
        kind = "ultimate-parent" if ultimate else "direct-parent"
        try:
            document = await self._client.get_json(
                f"{BASE_URL}/lei-records/{lei}/{kind}", external_id=f"{lei}/{kind}"
            )
        except NotFoundError:
            # GLEIF zwraca 404, gdy podmiot nie ma spółki dominującej — to poprawna
            # odpowiedź, nie awaria.
            return None
        data = document.payload.get("data")
        return data if isinstance(data, dict) else None

    @property
    def stats(self) -> dict[str, int]:
        return self._client.stats.as_dict()

    async def aclose(self) -> None:
        await self._client.aclose()


def _cursor_from_link(link: str) -> str | None:
    """Wyciąga wartość page[cursor] z linku `next` zwróconego przez API."""
    if not link:
        return None
    values = parse_qs(urlparse(link).query).get("page[cursor]")
    return values[0] if values else None
