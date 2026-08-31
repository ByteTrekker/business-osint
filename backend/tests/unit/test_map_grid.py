"""Reguły siatki mapy, które da się sprawdzić bez bazy.

Cała poprawność zwijania siatki opiera się na jednym warunku: każdy bok komórki
musi być **całkowitą** wielokrotnością komórki bazowej. Jeżeli przestanie być,
poziomy przybliżenia rozjadą się o ułamek komórki i skupiska zaczną przeskakiwać
przy zmianie przybliżenia — bez żadnego błędu, bez pustego wyniku, bez sygnału.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from business_osint.domain.map_grid import (
    SIATKA,
    SIATKA_BAZOWA,
    SZCZEGOL_OD,
    bok_komorki,
    zwielokrotnienie,
)


def test_every_zoom_level_cell_is_a_whole_multiple_of_the_base_cell() -> None:
    for zoom, bok in SIATKA.items():
        krotnosc = zwielokrotnienie(bok)
        assert krotnosc >= 1, zoom
        assert Decimal(krotnosc) * SIATKA_BAZOWA == bok, zoom


def test_cell_that_is_not_a_whole_multiple_is_rejected_instead_of_rounded() -> None:
    # 0,007 to 1,4 komórki bazowej. Zaokrąglenie w dół dałoby siatkę o połowę
    # gęstszą niż zadeklarowana i nikt by tego nie zauważył.
    with pytest.raises(ValueError) as blad:
        zwielokrotnienie(Decimal("0.007"))
    # Komunikat ma nazwać wartość, która nie pasuje. Bez niej ktoś dostaje
    # wyjątek przy dodawaniu poziomu przybliżenia i nie wie którego dotyczy.
    assert "0.007" in str(blad.value)
    assert str(SIATKA_BAZOWA) in str(blad.value)


def test_cells_get_smaller_as_zoom_grows() -> None:
    poziomy = sorted(SIATKA)
    boki = [SIATKA[z] for z in poziomy]
    assert boki == sorted(boki, reverse=True)


def test_detail_level_starts_right_above_the_finest_grid() -> None:
    # Luka między najgęstszą siatką a poziomem szczegółowym oznaczałaby
    # przybliżenie, na którym nie wiadomo, co pokazać.
    assert max(SIATKA) + 1 == SZCZEGOL_OD
    assert SIATKA[max(SIATKA)] == SIATKA_BAZOWA


def test_base_cell_matches_the_value_baked_into_migration_0011() -> None:
    # Siatka jest **policzona** w tej jednostce i zapisana w tabeli. Zmiana tej
    # stałej bez migracji przesunęłaby całą mapę względem danych.
    from pathlib import Path

    migracja = (
        Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0011_address_cells.py"
    ).read_text(encoding="utf-8")
    assert f'BAZA = "{SIATKA_BAZOWA}"' in migracja


def test_zoom_outside_the_grid_clamps_to_its_edges_instead_of_failing() -> None:
    # Leaflet potrafi zwrócić przybliżenie spoza `SIATKA` (własny `minZoom`,
    # animacja, wskazanie z zewnątrz). Wyjątek zamiast mapy byłby tu gorszy
    # niż najbliższy sensowny poziom.
    assert bok_komorki(1) == SIATKA[min(SIATKA)]
    assert bok_komorki(99) == SIATKA[max(SIATKA)]
    assert bok_komorki(9) == SIATKA[9]
