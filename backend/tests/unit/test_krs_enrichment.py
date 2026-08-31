"""Czyste funkcje wzbogacania KRS — bez bazy i bez sieci."""

from __future__ import annotations

import datetime as dt

from business_osint.etl.krs_enrichment import _as_date, _latest_capital


def test_current_capital_wins_over_historical_ones() -> None:
    """Kapitał bieżący to wpis bez daty zamknięcia, nie ostatni w tablicy."""
    history = [
        {"value": "525221421,25", "from": "2001-07-19", "to": "2003-11-20"},
        {"value": "1451177561,25", "from": "2022-11-02", "to": None},
    ]

    assert str(_latest_capital(history)) == "1451177561.25"


def test_unparsable_capital_does_not_explode() -> None:
    """Śmieć w kwocie ma dać ``None``, a nie wywrócić import."""
    assert _latest_capital([{"value": "brak danych", "from": None, "to": None}]) is None
    assert _latest_capital([]) is None


def test_date_is_parsed_from_the_registry_format() -> None:
    """asyncpg odrzuca napis tam, gdzie SQL deklaruje `date` — konwersja jest po naszej stronie."""
    assert _as_date("2001-07-19") == dt.date(2001, 7, 19)
    assert _as_date(dt.date(2001, 7, 19)) == dt.date(2001, 7, 19)


def test_missing_or_broken_date_gives_none() -> None:
    """Brak daty rejestracji nie może wywrócić wzbogacania."""
    assert _as_date(None) is None
    assert _as_date("brak") is None
