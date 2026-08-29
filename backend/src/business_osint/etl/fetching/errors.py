"""Taksonomia błędów pobierania.

Sens podziału: **retry ma sens tylko dla błędów przejściowych**. Ponawianie
odpowiedzi 400 albo 404 to marnowanie limitu zapytań i zaciemnianie logów.
"""

from __future__ import annotations


class FetchError(Exception):
    """Baza dla wszystkiego, co może pójść nie tak przy pobieraniu.

    Warstwa pobierania nie wypuszcza na zewnątrz wyjątków httpx ani asyncio —
    job ingestujący ma reagować na kategorię błędu, a nie na bibliotekę.
    """

    def __init__(self, message: str, *, source: str, url: str | None = None) -> None:
        super().__init__(message)
        self.source = source
        self.url = url


class NotFoundError(FetchError):
    """Zasób nie istnieje w rejestrze. Nie ponawiamy — to poprawna odpowiedź."""


class PermanentError(FetchError):
    """Błąd, którego ponowienie nie naprawi: zły format, brak autoryzacji, 4xx."""


class RetryableError(FetchError):
    """Błąd przejściowy: 5xx, 429, timeout, zerwane połączenie."""


class RetryBudgetExhaustedError(FetchError):
    """Wyczerpano liczbę prób. Zadanie wraca do kolejki, nie przerywa przebiegu."""

    def __init__(self, message: str, *, source: str, url: str | None, attempts: int) -> None:
        super().__init__(message, source=source, url=url)
        self.attempts = attempts


class CircuitOpenError(FetchError):
    """Bezpiecznik otwarty — rejestr jest niedostępny, nie dobijamy go dalej."""
