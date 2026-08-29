"""Biała lista podatników VAT (Ministerstwo Finansów).

Wartość tego źródła nie leży w statusie VAT, tylko w **moście identyfikatorowym**:
jeden rekord zawiera naraz NIP, REGON i KRS tego samego podmiotu. To jest
dokładnie ta informacja, której brakuje przy scalaniu encji pochodzących
z GLEIF (LEI + krajowy numer), REGON (REGON) i KRS (KRS).

API jest publiczne i nie wymaga klucza. Endpoint zbiorczy przyjmuje wiele
numerów w jednym zapytaniu, co pozwala zejść z tysięcy żądań do dziesiątek.
"""

from __future__ import annotations

from typing import Any

import httpx

from business_osint.domain.enums import SourceKind
from business_osint.etl.fetching.client import FetchedDocument, ResilientClient
from business_osint.etl.fetching.policy import RetryPolicy
from business_osint.etl.fetching.rate_limit import RateLimiter

BASE_URL = "https://wl-api.mf.gov.pl/api"

#: Limit numerów w jednym zapytaniu zbiorczym narzucony przez API.
MAX_NIPS_PER_REQUEST = 30
#: MF nie publikuje twardego limitu tempa; zostajemy przy ostrożnej wartości.
DEFAULT_RATE = 2.0

USER_AGENT = "business-osint/0.1 (+https://github.com/ByteTrekker/business-osint)"


class WhitelistClient:
    def __init__(self, client: ResilientClient | None = None) -> None:
        self._client = client or self._build_default()

    @staticmethod
    def _build_default() -> ResilientClient:
        return ResilientClient(
            source=SourceKind.MF_WHITELIST.value,
            client=httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            ),
            rate_limiter=RateLimiter(DEFAULT_RATE),
            retry_policy=RetryPolicy(max_attempts=4, initial_backoff=2.0),
        )

    async def fetch_batch(self, nips: list[str], *, date: str) -> FetchedDocument:
        """Pobiera dane dla partii numerów NIP (maks. ``MAX_NIPS_PER_REQUEST``)."""
        if not nips:
            raise ValueError("pusta lista numerów NIP")
        if len(nips) > MAX_NIPS_PER_REQUEST:
            raise ValueError(f"maksymalnie {MAX_NIPS_PER_REQUEST} numerów na zapytanie")
        joined = ",".join(nips)
        return await self._client.get_json(
            f"{BASE_URL}/search/nips/{joined}",
            external_id=f"nips/{date}/{joined[:64]}",
            params={"date": date},
        )

    @property
    def stats(self) -> dict[str, int]:
        return self._client.stats.as_dict()

    async def aclose(self) -> None:
        await self._client.aclose()


def extract_identifier_bridges(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Wyciąga trójki NIP/REGON/KRS oraz status VAT z odpowiedzi zbiorczej."""
    bridges: list[dict[str, str]] = []
    for entry in (payload.get("result") or {}).get("entries") or []:
        for subject in entry.get("subjects") or []:
            nip = (subject.get("nip") or "").strip()
            if not nip:
                continue
            bridges.append(
                {
                    "nip": nip,
                    "regon": (subject.get("regon") or "").strip(),
                    "krs": (subject.get("krs") or "").strip(),
                    "name": (subject.get("name") or "").strip(),
                    "status_vat": (subject.get("statusVat") or "").strip(),
                    "address": (
                        subject.get("workingAddress") or subject.get("residenceAddress") or ""
                    ).strip(),
                }
            )
    return bridges
