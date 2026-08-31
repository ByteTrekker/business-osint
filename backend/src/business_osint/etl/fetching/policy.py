"""Polityka ponawiania.

Czysta logika, bez I/O i bez zegara — dzięki temu wykładniczy backoff da się
przetestować w milisekundach, zamiast czekać na prawdziwe opóźnienia.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Parametry ponawiania dla jednego źródła.

    ``jitter`` jest obowiązkowy, nie kosmetyczny: bez losowego rozrzutu
    kilkuset workerów odbija się od rejestru w tej samej sekundzie i tworzy
    falę zapytań dokładnie wtedy, gdy serwis wraca do życia.
    """

    max_attempts: int = 5
    initial_backoff: float = 1.0
    max_backoff: float = 60.0
    multiplier: float = 2.0
    #: Ułamek opóźnienia, o który losowo modyfikujemy czas oczekiwania (0.25 = ±25%).
    jitter: float = 0.25
    #: Nagłówek Retry-After jest wiążący — serwer wie lepiej, kiedy wróci.
    respect_retry_after: bool = True
    #: Ale nie pozwalamy mu zablokować workera na godziny.
    max_retry_after: float = 300.0

    def backoff_for(
        self,
        attempt: int,
        *,
        retry_after: float | None = None,
        rng: random.Random | None = None,
    ) -> float:
        """Czas oczekiwania przed próbą numer ``attempt`` (liczoną od 1)."""
        if attempt < 1:
            raise ValueError("numer próby liczymy od 1")

        if retry_after is not None and self.respect_retry_after:
            return min(max(retry_after, 0.0), self.max_retry_after)

        delay = self.initial_backoff * (self.multiplier ** (attempt - 1))
        delay = min(delay, self.max_backoff)
        if self.jitter:
            generator = rng or random
            delay *= 1.0 + generator.uniform(-self.jitter, self.jitter)
        return max(delay, 0.0)

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts
