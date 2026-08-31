"""Siatka mapy zbiorczej — czysta arytmetyka poziomów przybliżenia.

Reguła, na której stoi cała mapa: **każdy bok komórki jest całkowitą
wielokrotnością komórki bazowej**. Tylko wtedy zwinięcie przeliczonej siatki
bazowej daje ten sam wynik co policzenie skupisk od zera. Gdy przestanie być
całkowitą wielokrotnością, poziomy przybliżenia rozjadą się o ułamek komórki:
skupiska zaczną przeskakiwać przy zmianie przybliżenia, liczby przestaną się
sumować — i nic tego nie zgłosi, bo mapa nadal będzie coś rysować.

Moduł jest w `domain/`, a nie przy zapytaniu, bo nie potrzebuje bazy — a przez
to obejmują go testy mutacyjne, które sprawdzają, czy ta reguła ma test
wykrywający jej zmianę.
"""

from __future__ import annotations

from decimal import Decimal

#: Bok komórki bazowej w stopniach. Ta wartość jest **zapisana w danych** —
#: tabela `address_cells` jest w niej policzona — więc jej zmiana wymaga
#: migracji i przeliczenia siatki, nie samej edycji tej stałej. Musi się
#: zgadzać ze stałą `BAZA` w migracji 0011.
SIATKA_BAZOWA = Decimal("0.005")

#: Bok komórki dla poziomów przybliżenia Leafleta.
#:
#: Wartości dobrane tak, żeby na typowym ekranie wychodziło kilkaset komórek —
#: dość, żeby zobaczyć kształt skupisk, za mało, żeby zadławić rysowanie.
SIATKA = {
    5: Decimal("0.5"),
    6: Decimal("0.25"),
    7: Decimal("0.2"),
    8: Decimal("0.1"),
    9: Decimal("0.05"),
    10: Decimal("0.025"),
    11: Decimal("0.02"),
    12: Decimal("0.01"),
    13: SIATKA_BAZOWA,
}

#: Od tego przybliżenia pokazujemy konkretne adresy zamiast skupisk. Przy
#: czternastu widać już pojedyncze ulice i klaster przestaje cokolwiek wyjaśniać.
SZCZEGOL_OD = 14

#: Twardy limit komórek w odpowiedzi. Zapytanie o cały kraj przy dużym
#: przybliżeniu wygenerowałoby ich setki tysięcy; wolimy przyciąć i **powiedzieć
#: o tym**, niż wysłać odpowiedź, której przeglądarka nie narysuje.
LIMIT_KOMOREK = 2000


def bok_komorki(zoom: int) -> Decimal:
    """Bok komórki dla poziomu przybliżenia, przycięty do zakresu siatki."""
    return SIATKA[min(max(zoom, min(SIATKA)), max(SIATKA))]


def zwielokrotnienie(cell: Decimal) -> int:
    """Ile komórek bazowych mieści się w boku komórki dla danego przybliżenia.

    Liczone na `Decimal`, nie na `float`: `0.2 / 0.005` w arytmetyce
    zmiennoprzecinkowej wychodzi 39,999…, a `int()` z tego to 39 — czyli siatka
    przesunięta o jedną komórkę na każdym poziomie, na którym to wyjdzie.
    """
    iloraz = cell / SIATKA_BAZOWA
    if iloraz != iloraz.to_integral_value():
        raise ValueError(f"Bok {cell} nie jest wielokrotnością {SIATKA_BAZOWA}")
    return int(iloraz)
