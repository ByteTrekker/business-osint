"""Bezpiecznik (circuit breaker).

Po co: gdy rejestr przestaje odpowiadać, samo ponawianie zamienia się w atak
na cudzą infrastrukturę i wypala limit zapytań. Bezpiecznik po serii błędów
przestaje wypuszczać ruch, a po ustalonym czasie próbuje jednego zapytania
rozpoznawczego.

Stan: CLOSED (przepuszczamy) -> OPEN (odcinamy) -> HALF_OPEN (jedna próba).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._state = CircuitState.CLOSED

    @property
    def state(self) -> CircuitState:
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self._reset_timeout
        ):
            self._state = CircuitState.HALF_OPEN
        return self._state

    def allow(self) -> bool:
        """Czy wolno wykonać zapytanie."""
        return self.state is not CircuitState.OPEN

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        # Nieudana próba rozpoznawcza natychmiast otwiera bezpiecznik z powrotem.
        if self.state is CircuitState.HALF_OPEN:
            self._trip()
            return
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
