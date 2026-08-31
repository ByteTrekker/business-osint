"""Odporny klient HTTP dla rejestrów publicznych.

Składa w całość: limit tempa, ponawianie z wykładniczym backoffem, bezpiecznik
i mapowanie wyjątków biblioteki na taksonomię dziedzinową. Kontrakt:

* metoda **nigdy** nie wypuszcza wyjątku httpx ani asyncio — tylko ``FetchError``;
* pojedyncze zadanie, które się nie udało, nie przerywa przebiegu ETL;
* każda odpowiedź jest opakowana w ``FetchedDocument`` razem z sha256, więc
  provenance powstaje w tym samym miejscu, co pobranie.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from business_osint.etl.fetching.circuit import CircuitBreaker
from business_osint.etl.fetching.errors import (
    CircuitOpenError,
    FetchError,
    NotFoundError,
    PermanentError,
    RetryableError,
    RetryBudgetExhaustedError,
)
from business_osint.etl.fetching.policy import RetryPolicy
from business_osint.etl.fetching.rate_limit import RateLimiter

#: Kody, po których ma sens ponowienie. 408 i 425 są rzadkie, ale przejściowe.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504, 507, 509})


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    """Surowa odpowiedź plus metadane wymagane przez provenance."""

    source: str
    external_id: str
    url: str
    fetched_at: datetime
    payload: dict[str, Any]
    content_sha256: str
    attempts: int = 1

    @classmethod
    def build(
        cls,
        *,
        source: str,
        external_id: str,
        url: str,
        payload: dict[str, Any],
        attempts: int = 1,
    ) -> FetchedDocument:
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return cls(
            source=source,
            external_id=external_id,
            url=url,
            fetched_at=datetime.now(UTC),
            payload=payload,
            content_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
            attempts=attempts,
        )


@dataclass(slots=True)
class FetchStats:
    """Liczniki jednego klienta — trafiają do ``ingestion_runs.stats``."""

    requests: int = 0
    retries: int = 0
    failures: int = 0
    not_found: int = 0
    circuit_trips: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "retries": self.retries,
            "failures": self.failures,
            "not_found": self.not_found,
            "circuit_trips": self.circuit_trips,
        }


class ResilientClient:
    """Klient HTTP z limitem tempa, ponawianiem i bezpiecznikiem."""

    def __init__(
        self,
        *,
        source: str,
        client: httpx.AsyncClient,
        rate_limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.source = source
        self._client = client
        self._limiter = rate_limiter
        self._policy = retry_policy or RetryPolicy()
        self._breaker = circuit_breaker or CircuitBreaker()
        self._sleep = sleep
        # S311: to jest rozrzut czasu ponowienia, nie materiał kryptograficzny.
        self._rng = rng or random.Random()  # noqa: S311
        self.stats = FetchStats()

    async def get_json(
        self,
        url: str,
        *,
        external_id: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchedDocument:
        """Pobiera JSON. Rzuca wyłącznie podklasy ``FetchError``."""
        attempt = 0
        last_error: FetchError | None = None

        while True:
            attempt += 1
            if not self._breaker.allow():
                self.stats.circuit_trips += 1
                raise CircuitOpenError(
                    f"bezpiecznik otwarty dla źródła {self.source}",
                    source=self.source,
                    url=url,
                )

            if self._limiter is not None:
                await self._limiter.acquire()

            try:
                self.stats.requests += 1
                response = await self._client.get(url, params=params, headers=headers)
                payload = self._payload_or_raise(response, url)
            except NotFoundError:
                self.stats.not_found += 1
                self._breaker.record_success()  # 404 to poprawna odpowiedź serwera
                raise
            except PermanentError:
                self.stats.failures += 1
                self._breaker.record_success()  # wina jest po naszej stronie, nie serwera
                raise
            except RetryableError as error:
                last_error = error
                self._breaker.record_failure()
            except httpx.HTTPError as error:
                # Timeouty i zerwane połączenia — biblioteka nie wychodzi na zewnątrz.
                last_error = RetryableError(
                    f"{type(error).__name__}: {error}", source=self.source, url=url
                )
                self._breaker.record_failure()
            except (ValueError, json.JSONDecodeError) as error:
                self.stats.failures += 1
                self._breaker.record_success()
                raise PermanentError(
                    f"odpowiedź nie jest poprawnym JSON-em: {error}",
                    source=self.source,
                    url=url,
                ) from error
            else:
                self._breaker.record_success()
                return FetchedDocument.build(
                    source=self.source,
                    external_id=external_id,
                    url=str(response.url),
                    payload=payload,
                    attempts=attempt,
                )

            if not self._policy.should_retry(attempt):
                self.stats.failures += 1
                raise RetryBudgetExhaustedError(
                    f"wyczerpano {attempt} prób: {last_error}",
                    source=self.source,
                    url=url,
                    attempts=attempt,
                ) from last_error

            self.stats.retries += 1
            delay = self._policy.backoff_for(
                attempt,
                retry_after=getattr(last_error, "retry_after", None),
                rng=self._rng,
            )
            await self._sleep(delay)

    def _payload_or_raise(self, response: httpx.Response, url: str) -> dict[str, Any]:
        status = response.status_code
        if status == 404:
            raise NotFoundError(f"zasób nie istnieje ({url})", source=self.source, url=url)
        if status in RETRYABLE_STATUS:
            error = RetryableError(f"HTTP {status}", source=self.source, url=url)
            error.retry_after = _retry_after_seconds(response)  # type: ignore[attr-defined]
            raise error
        if status >= 400:
            raise PermanentError(f"HTTP {status}", source=self.source, url=url)

        payload = response.json()
        if not isinstance(payload, dict):
            # Część rejestrów zwraca listę na najwyższym poziomie — opakowujemy,
            # żeby provenance zawsze miało obiekt do zahaszowania.
            return {"items": payload}
        return payload

    async def aclose(self) -> None:
        await self._client.aclose()


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Nagłówek Retry-After w sekundach; ignorujemy wariant z datą HTTP."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


async def gather_resilient(
    tasks: list[Callable[[], Awaitable[Any]]],
    *,
    concurrency: int,
) -> list[Any | FetchError]:
    """Uruchamia zadania równolegle; błąd jednego nie przerywa pozostałych.

    Zwraca listę wyników **albo** wyjątków w kolejności wejściowej. To jest
    całe „żeby nie padało” na poziomie przebiegu: worker zapisuje sukcesy,
    a nieudane zadania odkłada do ponowienia w kolejnej turze.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def run(task: Callable[[], Awaitable[Any]]) -> Any | FetchError:
        async with semaphore:
            try:
                return await task()
            except FetchError as error:
                return error

    return list(await asyncio.gather(*(run(task) for task in tasks)))
