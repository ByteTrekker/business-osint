"""Ograniczanie tempa zapytań (token bucket).

Zegar i funkcja usypiania są wstrzykiwane, więc testy nie czekają realnego czasu.
Limiter jest współdzielony przez wszystkie zadania danego źródła — inaczej
dziesięciu workerów mnożyłoby dozwolone tempo przez dziesięć.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class RateLimiter:
    """Token bucket: ``rate`` żetonów na sekundę, pojemność ``burst``."""

    def __init__(
        self,
        rate_per_second: float,
        *,
        burst: int = 1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("tempo musi być dodatnie")
        self._rate = rate_per_second
        self._burst = max(1, burst)
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(self._burst)
        self._updated_at = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Czeka, aż będzie wolno wykonać kolejne zapytanie."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                missing = 1.0 - self._tokens
                wait = missing / self._rate
            # Czekamy poza sekcją krytyczną, żeby nie blokować pozostałych zadań.
            await self._sleep(wait)

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._updated_at)
        self._updated_at = now
        self._tokens = min(float(self._burst), self._tokens + elapsed * self._rate)

    @property
    def available_tokens(self) -> float:
        self._refill()
        return self._tokens
