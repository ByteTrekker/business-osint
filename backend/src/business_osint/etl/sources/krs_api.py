"""Klient oficjalnego API Ministerstwa Sprawiedliwości (KRS).

Endpointy (stan na 2026-08, do zweryfikowania przed produkcją):

* ``GET https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json``
* ``GET https://api-krs.ms.gov.pl/api/krs/OdpisPelny/{krs}?rejestr=P&format=json``

Odpis PEŁNY zawiera wykreślone wpisy — to on daje historię („był członkiem zarządu
2020–2023”). Odpis aktualny to tylko stan bieżący. Do budowy grafu historycznego
pobieramy pełny, do codziennego odświeżania — aktualny.

Limity: API jest publiczne, ale bez SLA. Trzymamy się ~1 req/s, retry z backoffem
i ZAWSZE zapisujemy surową odpowiedź do ``raw_documents`` przed parsowaniem.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

BASE_URL = "https://api-krs.ms.gov.pl/api/krs"
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    """Surowa odpowiedź + metadane potrzebne do provenance."""

    external_id: str
    url: str
    fetched_at: datetime
    payload: dict[str, Any]
    content_sha256: str

    @classmethod
    def build(cls, external_id: str, url: str, payload: dict[str, Any]) -> FetchedDocument:
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return cls(
            external_id=external_id,
            url=url,
            fetched_at=datetime.now(UTC),
            payload=payload,
            content_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
        )


class KrsClient:
    """Minimalny klient z rate-limitem i retry."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        requests_per_second: float = 1.0,
        max_retries: int = 3,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        self._min_interval = 1.0 / requests_per_second
        self._max_retries = max_retries
        self._lock = asyncio.Lock()

    async def fetch_full(self, krs: str, *, registry: str = "P") -> FetchedDocument:
        """Odpis pełny — zawiera wpisy wykreślone, czyli historię powiązań."""
        return await self._fetch("OdpisPelny", krs, registry)

    async def fetch_current(self, krs: str, *, registry: str = "P") -> FetchedDocument:
        return await self._fetch("OdpisAktualny", krs, registry)

    async def _fetch(self, kind: str, krs: str, registry: str) -> FetchedDocument:
        url = f"{BASE_URL}/{kind}/{krs}"
        params = {"rejestr": registry, "format": "json"}
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            async with self._lock:  # prosty globalny rate-limit
                await asyncio.sleep(self._min_interval)
            try:
                response = await self._client.get(url, params=params)
                if response.status_code == 404:
                    raise LookupError(f"KRS {krs} nie istnieje w rejestrze {registry}")
                if response.status_code >= 500 or response.status_code == 429:
                    raise httpx.HTTPStatusError(
                        "retryable", request=response.request, response=response
                    )
                response.raise_for_status()
                return FetchedDocument.build(krs, str(response.url), response.json())
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_error = exc
                await asyncio.sleep(2**attempt)
        raise RuntimeError(f"Nie udało się pobrać KRS {krs}") from last_error

    async def aclose(self) -> None:
        await self._client.aclose()
