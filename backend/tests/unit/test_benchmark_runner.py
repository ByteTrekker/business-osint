"""Czyste funkcje runnera pomiarowego.

Runner leży poza pakietem (`ops/benchmark/run.py`), bo ma działać na czystym
systemie, bez instalowania czegokolwiek z tego projektu — inaczej nie da się
nim porównać implementacji w innym języku. Ładujemy go po ścieżce.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys


def _znajdz_runner() -> pathlib.Path:
    """Szuka runnera w górę drzewa, zamiast liczyć poziomy katalogów.

    Ścieżka względna o stałej liczbie `parents[...]` łamie się w piaskownicy
    testów mutacyjnych, która kopiuje drzewo w inne miejsce. Szukanie w górę
    działa w obu układach.
    """
    for katalog in pathlib.Path(__file__).resolve().parents:
        kandydat = katalog / "ops" / "benchmark" / "run.py"
        if kandydat.exists():
            return kandydat
    raise FileNotFoundError("nie znaleziono ops/benchmark/run.py")


_SCIEZKA = _znajdz_runner()
_spec = importlib.util.spec_from_file_location("bench_runner", _SCIEZKA)
assert _spec and _spec.loader
bench = importlib.util.module_from_spec(_spec)
sys.modules["bench_runner"] = bench
_spec.loader.exec_module(bench)


def test_percentile_returns_a_value_that_actually_occurred() -> None:
    """Bez interpolacji: p95 ma być czasem, który naprawdę zmierzono.

    Interpolacja daje liczbę, której żadne żądanie nie osiągnęło — ładniejszą,
    ale nieprawdziwą.
    """
    probki = [float(i) for i in range(1, 101)]

    assert bench.percentyl(probki, 0.95) in probki
    assert bench.percentyl(probki, 0.50) in probki


def test_percentile_is_monotonic() -> None:
    """p50 ≤ p95 ≤ p99 — inaczej raport jest wewnętrznie sprzeczny."""
    probki = [5.0, 1.0, 9.0, 3.0, 7.0, 2.0, 8.0, 4.0, 6.0, 10.0]

    assert (
        bench.percentyl(probki, 0.50)
        <= bench.percentyl(probki, 0.95)
        <= bench.percentyl(probki, 0.99)
    )


def test_percentile_of_nothing_is_zero_not_an_error() -> None:
    """Scenariusz, w którym każde żądanie padło, ma dać raport, nie wyjątek."""
    assert bench.percentyl([], 0.95) == 0.0


def test_single_sample_is_its_own_percentile() -> None:
    assert bench.percentyl([42.0], 0.99) == 42.0


def test_result_count_reads_every_envelope_shape() -> None:
    """Kontrakt ma trzy kształty odpowiedzi i pomiar musi rozumieć wszystkie.

    Liczba wyników jest tu równie ważna jak czas: implementacja zwracająca mniej
    rekordów wychodzi na szybszą, a nie jest.
    """
    assert bench.policz_wyniki({"hits": [1, 2, 3]}) == 3
    assert bench.policz_wyniki({"items": [1, 2]}) == 2
    assert bench.policz_wyniki({"nodes": [1]}) == 1
    assert bench.policz_wyniki([1, 2, 3, 4]) == 4


def test_a_single_object_counts_as_one_result() -> None:
    """Profil podmiotu to jedna odpowiedź, nie zero."""
    assert bench.policz_wyniki({"id": "x", "name": "ALFA"}) == 1


def test_empty_response_counts_as_zero() -> None:
    assert bench.policz_wyniki({}) == 0
    assert bench.policz_wyniki([]) == 0
    assert bench.policz_wyniki(None) == 0


def test_comparison_refuses_different_datasets() -> None:
    """Dwa przebiegi na różnych danych są nieporównywalne.

    Zwracamy kod błędu zamiast tabeli, bo tabela sugerowałaby, że różnice czasów
    coś znaczą — a mogą wynikać wyłącznie z wielkości zbioru.
    """
    przed = {"zbior": {"entities": 100}, "scenariusze": []}
    po = {"zbior": {"entities": 200}, "scenariusze": []}

    assert bench.porownaj(przed, po) == 1


def test_noise_below_the_absolute_floor_is_not_a_regression() -> None:
    """Na szybkim scenariuszu sam próg względny produkuje fałszywe alarmy.

    Zmierzone: przy 1,7 ms wahnięcie planisty systemu o 0,7 ms to „43%".
    Dlatego regresja wymaga przekroczenia **obu** progów.
    """
    przed = {
        "zbior": {"entities": 1},
        "scenariusze": [
            {"nazwa": "szybki", "p95_ms": 1.7, "wynikow": 5, "poprawny": True},
        ],
    }
    po = {
        "zbior": {"entities": 1},
        "scenariusze": [
            {"nazwa": "szybki", "p95_ms": 2.4, "wynikow": 5, "poprawny": True},
        ],
    }

    assert bench.porownaj(przed, po) == 0


def test_a_real_slowdown_is_still_reported() -> None:
    """Próg bezwzględny nie może zagłuszyć prawdziwego spowolnienia."""
    przed = {
        "zbior": {"entities": 1},
        "scenariusze": [{"nazwa": "graf", "p95_ms": 20.0, "wynikow": 16, "poprawny": True}],
    }
    po = {
        "zbior": {"entities": 1},
        "scenariusze": [{"nazwa": "graf", "p95_ms": 60.0, "wynikow": 16, "poprawny": True}],
    }

    assert bench.porownaj(przed, po) == 1


def test_fewer_results_is_a_regression_even_when_faster() -> None:
    """To jest najważniejsza reguła tego narzędzia.

    Implementacja, która zwraca mniej wyników, prawie zawsze jest szybsza.
    Bez tego sprawdzenia benchmark nagradzałby psucie wyszukiwarki.
    """
    przed = {
        "zbior": {"entities": 1},
        "scenariusze": [{"nazwa": "szukaj", "p95_ms": 100.0, "wynikow": 20, "poprawny": True}],
    }
    po = {
        "zbior": {"entities": 1},
        "scenariusze": [{"nazwa": "szukaj", "p95_ms": 10.0, "wynikow": 3, "poprawny": True}],
    }

    assert bench.porownaj(przed, po) == 1
