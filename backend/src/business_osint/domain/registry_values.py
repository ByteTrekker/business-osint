"""Odczyt wartości z dokumentów rejestrowych — bez I/O.

Rejestry podają daty i kwoty jako napisy, w zapisie, który bywa niekompletny
albo po prostu błędny. Zamiana ich na typy Pythona jest czystą regułą i mieszka
tutaj, a nie w module wzbogacania — tam ciągnęłaby za sobą sesję bazy do
każdego testu.

To nie jest podział teoretyczny. Te dwie funkcje stały wcześniej w
`etl/krs_enrichment`, a ich test jednostkowy importował ten moduł razem z całą
warstwą bazy. Piaskownica testów mutacyjnych kopiuje wyłącznie `domain/`
i `etl/`, więc import się wywracał, mutmut nie startował — i bramka mutacyjna
przez cztery zmiany z rzędu przepuszczała wszystko, meldując zielono.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any


def parse_registry_date(value: Any) -> dt.date | None:
    """Data z rejestru albo ``None``. Brak daty nie może wywrócić importu.

    asyncpg wnioskuje typ parametru z ``CAST(... AS date)`` i **odrzuca napis**,
    więc konwersja musi się wydarzyć po stronie Pythona. Ani ruff, ani mypy tego
    nie zobaczą — to surowy SQL, wychodzi dopiero na żywym połączeniu.

    >>> parse_registry_date("2001-07-19")
    datetime.date(2001, 7, 19)
    >>> parse_registry_date("brak") is None
    True
    """
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def current_value(history: list[dict[str, Any]]) -> str | None:
    """Obowiązujący wpis z datowanej historii, czyli ten bez daty zamknięcia.

    Nie „ostatni w tablicy": rejestr potrafi podać wpisy w kolejności innej niż
    chronologiczna, a wtedy wzięcie ostatniego dałoby wartość historyczną
    wyglądającą na bieżącą.

    >>> current_value([{"value": "a", "to": "2020-01-01"}, {"value": "b", "to": None}])
    'b'
    """
    current = [entry for entry in history if entry.get("to") is None]
    chosen = current[-1] if current else (history[-1] if history else None)
    if chosen is None:
        return None
    value = chosen.get("value")
    return None if value is None else str(value)


def parse_registry_amount(value: Any) -> Decimal | None:
    """Kwota z rejestru. Polski zapis używa przecinka, czasem ze spacjami.

    >>> parse_registry_amount("1 451 177 561,25")
    Decimal('1451177561.25')
    >>> parse_registry_amount("brak danych") is None
    True
    """
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return None
