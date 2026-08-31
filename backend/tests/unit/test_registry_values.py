"""Odczyt wartości z dokumentów rejestrowych."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from business_osint.domain.registry_values import (
    current_value,
    parse_registry_amount,
    parse_registry_date,
)


def test_registry_date_is_parsed_from_the_iso_prefix() -> None:
    """Rejestr podaje daty jako napis; asyncpg wymaga `date` i odrzuca napis."""
    assert parse_registry_date("2001-07-19") == dt.date(2001, 7, 19)
    assert parse_registry_date("2001-07-19T00:00:00Z") == dt.date(2001, 7, 19)


def test_a_date_object_passes_through_unchanged() -> None:
    assert parse_registry_date(dt.date(2001, 7, 19)) == dt.date(2001, 7, 19)


def test_missing_or_broken_date_gives_none_instead_of_raising() -> None:
    """Brak daty rejestracji nie może wywrócić wzbogacania całego podmiotu."""
    assert parse_registry_date(None) is None
    assert parse_registry_date("brak") is None
    assert parse_registry_date("") is None


def test_open_entry_wins_over_the_last_one_in_the_list() -> None:
    """Obowiązujący jest wpis bez daty zamknięcia, a nie ostatni w tablicy.

    Rejestr potrafi podać wpisy w kolejności innej niż chronologiczna. Wzięcie
    ostatniego dałoby wtedy wartość historyczną wyglądającą na bieżącą.
    """
    history = [
        {"value": "b", "to": None},
        {"value": "a", "to": "2003-11-20"},
    ]

    assert current_value(history) == "b"


def test_history_with_every_entry_closed_falls_back_to_the_last() -> None:
    """Gdy wszystko jest zamknięte, ostatni wpis jest najlepszym przybliżeniem.

    Trzy wpisy, nie dwa: przy dwóch „ostatni" i „drugi" to ten sam element,
    więc test nie odróżniłby sięgnięcia po niewłaściwy koniec listy.
    """
    history = [
        {"value": "a", "to": "2003-11-20"},
        {"value": "b", "to": "2010-01-01"},
        {"value": "c", "to": "2020-01-01"},
    ]

    assert current_value(history) == "c"


def test_empty_history_gives_none() -> None:
    assert current_value([]) is None


def test_entry_without_a_value_gives_none() -> None:
    assert current_value([{"to": None}]) is None


def test_polish_amount_notation_is_understood() -> None:
    """Kwoty w rejestrze mają przecinek dziesiętny, czasem spacje tysięczne."""
    assert parse_registry_amount("1 451 177 561,25") == Decimal("1451177561.25")
    assert parse_registry_amount("525221421,25") == Decimal("525221421.25")


def test_unparsable_amount_gives_none_instead_of_raising() -> None:
    """Śmieć w kwocie ma dać `None`, a nie wywrócić import."""
    assert parse_registry_amount("brak danych") is None
    assert parse_registry_amount(None) is None
