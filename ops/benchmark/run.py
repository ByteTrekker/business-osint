#!/usr/bin/env python3
"""Pomiar wydajności przez kontrakt HTTP — niezależny od technologii.

Dlaczego nie przez SQL. Poprzedni benchmark (`ops/bench.sql`) mierzył plany
zapytań PostgreSQL. To użyteczne przy strojeniu indeksów, ale bezwartościowe
przy pytaniu „czy po przepisaniu na Go jest szybciej": nowa implementacja nie
ma tych zapytań, a może nie mieć nawet tej bazy.

Ten runner widzi tylko to, co widzi przeglądarka: adres HTTP i odpowiedź.
Dopóki nowa wersja wystawia ten sam kontrakt, ten sam plik scenariuszy mierzy
ją bez żadnej zmiany.

Świadomie **wyłącznie biblioteka standardowa**. Narzędzie do porównywania
technologii nie może samo wymagać instalowania jednej z nich; `python3 run.py`
ma zadziałać na czystym systemie.

Trzy decyzje, które odróżniają ten pomiar od licznika czasu:

* **Percentyle, nie średnia.** Średnia ukrywa ogon, a użytkownik czuje właśnie
  ogon. Raportujemy p50, p95 i p99.
* **Liczba wyników obok czasu.** Implementacja, która zwraca mniej wyników,
  wychodzi na szybszą. To najczęstszy sposób, w jaki benchmark zaczyna kłamać,
  więc każdy scenariusz deklaruje minimalną poprawną liczbę wyników.
* **Odcisk zbioru danych.** Dwa przebiegi na różnych danych są nieporównywalne
  i `porownaj` odmawia ich zestawiania.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Ile żądań wykonać przed pomiarem. Pierwsze wywołanie po starcie potrafi być
#: dwa rzędy wielkości wolniejsze (zimny bufor bazy, brak planu zapytania),
#: więc bez rozgrzewki mierzylibyśmy głównie stan cache.
ROZGRZEWKA = 3

#: Ile żądań mierzyć. Trzydzieści wystarcza na sensowny p95 i nie zamienia
#: pomiaru w test obciążeniowy — to nie to samo zadanie.
POWTORZENIA = 30

#: Powyżej tego progu różnica między przebiegami jest raportowana jako zmiana,
#: a nie szum.
#:
#: Wartość jest **zmierzona**, nie wybrana: dwa kolejne przebiegi na tym samym
#: kodzie i tych samych danych różniły się do 44%, dopóki rozgrzewka obejmowała
#: tylko pojedynczy scenariusz. Po rozgrzaniu całego zestawu rozrzut spada, ale
#: nadal sięga kilkunastu procent — próg poniżej tej granicy zamieniłby narzędzie
#: w generator fałszywych alarmów.
PROG_ZMIANY = 0.25

#: Zmiana musi przekroczyć **oba** progi: względny i bezwzględny. Sam względny
#: jest bezużyteczny przy szybkich scenariuszach — na 1,7 ms wahnięcie planisty
#: systemu o 0,7 ms to „43% regresji". Zmierzone: po rozgrzaniu całego zestawu
#: scenariusze poniżej 10 ms potrafiły dać 36% i 43% różnicy przy identycznym
#: kodzie, a w milisekundach było to poniżej jednej.
PROG_MS = 3.0


@dataclass(slots=True)
class WynikScenariusza:
    nazwa: str
    mierzy: str
    probek: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    wynikow: int
    bledow: int
    poprawny: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "nazwa": self.nazwa,
            "mierzy": self.mierzy,
            "probek": self.probek,
            "p50_ms": round(self.p50_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "min_ms": round(self.min_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "wynikow": self.wynikow,
            "bledow": self.bledow,
            "poprawny": self.poprawny,
        }


@dataclass(slots=True)
class Przebieg:
    baza: str
    zbior: dict[str, Any]
    wyniki: list[WynikScenariusza] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "baza": self.baza,
            "zbior": self.zbior,
            "scenariusze": [w.as_dict() for w in self.wyniki],
        }


def percentyl(probki: list[float], p: float) -> float:
    """Percentyl metodą najbliższej rangi — bez interpolacji.

    Interpolacja daje liczbę, której żadne żądanie nie osiągnęło. Przy trzydziestu
    próbkach wolimy powiedzieć „takie żądanie naprawdę było" niż podać ładniejszą
    wartość pośrednią.
    """
    if not probki:
        return 0.0
    uporzadkowane = sorted(probki)
    indeks = max(0, min(len(uporzadkowane) - 1, int(round(p * len(uporzadkowane) + 0.5)) - 1))
    return uporzadkowane[indeks]


def policz_wyniki(odpowiedz: Any) -> int:
    """Ile rekordów zwróciła odpowiedź — niezależnie od kształtu koperty.

    Kontrakt ma trzy kształty (lista, `hits`, `items`) i benchmark nie powinien
    wiedzieć, który endpoint ma który. Profil pojedynczego podmiotu liczy się
    jako jeden wynik.
    """
    if isinstance(odpowiedz, list):
        return len(odpowiedz)
    if isinstance(odpowiedz, dict):
        for klucz in ("hits", "items", "nodes"):
            if isinstance(odpowiedz.get(klucz), list):
                return len(odpowiedz[klucz])
        return 1 if odpowiedz else 0
    return 0


def pobierz(url: str, *, timeout: float = 60.0) -> tuple[Any, float]:
    """Zwraca (treść, czas w milisekundach). Błąd HTTP zwraca ``None``."""
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as odpowiedz:  # noqa: S310
            tresc = json.loads(odpowiedz.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None, (time.perf_counter() - start) * 1000
    return tresc, (time.perf_counter() - start) * 1000


def zbuduj_url(baza: str, sciezka: str, parametry: dict[str, Any] | None) -> str:
    zapytanie = f"?{urllib.parse.urlencode(parametry)}" if parametry else ""
    return f"{baza.rstrip('/')}{sciezka}{zapytanie}"


def rozwiaz_podmioty(baza: str, definicje: dict[str, Any]) -> dict[str, str]:
    """Zamienia numery rejestrowe na lokalne identyfikatory encji.

    Scenariusze wskazują podmioty numerem KRS albo nazwą, nigdy identyfikatorem:
    UUID jest lokalny dla instalacji i zmienia się przy każdym imporcie, a numer
    rejestrowy jest ten sam wszędzie. Dzięki temu ten sam plik scenariuszy działa
    na cudzej kopii bazy i po przepisaniu aplikacji.
    """
    rozwiazane: dict[str, str] = {}
    for nazwa, definicja in definicje.items():
        parametry: dict[str, Any] = {"q": definicja["szukaj"], "limit": 5}
        if "typ" in definicja:
            parametry["type"] = definicja["typ"]
        tresc, _ = pobierz(zbuduj_url(baza, "/search", parametry))
        trafienia = (tresc or {}).get("hits") or []
        if not trafienia:
            raise SystemExit(
                f"Nie udało się rozwiązać podmiotu „{nazwa}” "
                f"(szukano: {definicja['szukaj']!r}). Zbiór danych nie zawiera "
                f"podmiotów, na których oparte są scenariusze — pomiar byłby "
                f"nieporównywalny z innymi."
            )
        rozwiazane[nazwa] = trafienia[0]["id"]
    return rozwiazane


def zmierz(baza: str, scenariusz: dict[str, Any], podmioty: dict[str, str]) -> WynikScenariusza:
    sciezka = scenariusz["sciezka"].format(**podmioty)
    url = zbuduj_url(baza, sciezka, scenariusz.get("parametry"))

    for _ in range(ROZGRZEWKA):
        pobierz(url)

    czasy: list[float] = []
    bledow = 0
    wynikow = 0
    for _ in range(POWTORZENIA):
        tresc, ms = pobierz(url)
        if tresc is None:
            bledow += 1
            continue
        czasy.append(ms)
        wynikow = policz_wyniki(tresc)

    return WynikScenariusza(
        nazwa=scenariusz["nazwa"],
        mierzy=scenariusz.get("mierzy", ""),
        probek=len(czasy),
        p50_ms=percentyl(czasy, 0.50),
        p95_ms=percentyl(czasy, 0.95),
        p99_ms=percentyl(czasy, 0.99),
        min_ms=min(czasy) if czasy else 0.0,
        max_ms=max(czasy) if czasy else 0.0,
        wynikow=wynikow,
        bledow=bledow,
        poprawny=bledow == 0 and wynikow >= scenariusz.get("oczekiwane_min", 0),
    )


def uruchom(baza: str, plik: Path) -> Przebieg:
    definicja = json.loads(plik.read_text(encoding="utf-8"))
    zbior, _ = pobierz(zbuduj_url(baza, "/stats", None))
    if zbior is None:
        raise SystemExit(
            f"Brak odpowiedzi z {baza}/stats. Bez odcisku zbioru danych pomiar "
            f"nie da się z niczym porównać, więc nie zaczynam."
        )

    przebieg = Przebieg(baza=baza, zbior=zbior)
    podmioty = rozwiaz_podmioty(baza, definicja["podmioty"])

    # Rozgrzewka **całego zestawu** przed pomiarem czegokolwiek, nie tylko
    # pojedynczego scenariusza tuż przed nim. Bufor bazy jest wspólny: pierwszy
    # przebieg po starcie wychodził systematycznie o 16–44% wolniej od drugiego
    # przy identycznym kodzie, bo dane dociągały się dopiero w trakcie. Bez tego
    # narzędzie meldowałoby przyspieszenie tam, gdzie nic się nie zmieniło.
    for scenariusz in definicja["scenariusze"]:
        url = zbuduj_url(
            baza, scenariusz["sciezka"].format(**podmioty), scenariusz.get("parametry")
        )
        for _ in range(ROZGRZEWKA):
            pobierz(url)

    for scenariusz in definicja["scenariusze"]:
        wynik = zmierz(baza, scenariusz, podmioty)
        przebieg.wyniki.append(wynik)
        stan = "OK  " if wynik.poprawny else "BŁĄD"
        print(
            f"{stan} {wynik.nazwa:34} p50={wynik.p50_ms:8.2f} ms  "
            f"p95={wynik.p95_ms:8.2f} ms  wyników={wynik.wynikow}"
        )
    return przebieg


def porownaj(przed: dict[str, Any], po: dict[str, Any]) -> int:
    """Zestawia dwa przebiegi. Zwraca kod wyjścia: 1, gdy jest regresja."""
    if przed["zbior"] != po["zbior"]:
        print("UWAGA: przebiegi wykonano na RÓŻNYCH zbiorach danych.")
        print("       Porównanie czasów nie ma sensu — różnice mogą wynikać")
        print("       z wielkości danych, a nie ze zmian w aplikacji.")
        for klucz in sorted(set(przed["zbior"]) | set(po["zbior"])):
            a, b = przed["zbior"].get(klucz), po["zbior"].get(klucz)
            if a != b:
                print(f"       {klucz}: {a} -> {b}")
        return 1

    stare = {s["nazwa"]: s for s in przed["scenariusze"]}
    regresje = 0
    print(f"{'scenariusz':34} {'p95 przed':>11} {'p95 po':>11} {'zmiana':>9}")
    for nowy in po["scenariusze"]:
        stary = stare.get(nowy["nazwa"])
        if stary is None:
            print(f"{nowy['nazwa']:34} {'—':>11} {nowy['p95_ms']:>11.2f} {'nowy':>9}")
            continue
        # Dzielenie przez zero jest realne: scenariusz może się wykonać poniżej
        # rozdzielczości zegara przy trafieniu w cache.
        podstawa = max(stary["p95_ms"], 0.01)
        roznica_ms = nowy["p95_ms"] - stary["p95_ms"]
        zmiana = roznica_ms / podstawa
        znacznik = ""
        if not nowy["poprawny"]:
            znacznik = "  NIEPOPRAWNY WYNIK"
            regresje += 1
        elif stary["wynikow"] != nowy["wynikow"]:
            # Zmiana liczby wyników unieważnia porównanie czasu: szybciej przy
            # mniejszej odpowiedzi to nie jest przyspieszenie.
            znacznik = f"  wyników {stary['wynikow']} -> {nowy['wynikow']}"
            regresje += 1
        elif zmiana > PROG_ZMIANY and roznica_ms > PROG_MS:
            znacznik = "  REGRESJA"
            regresje += 1
        elif zmiana < -PROG_ZMIANY and roznica_ms < -PROG_MS:
            znacznik = "  szybciej"
        print(
            f"{nowy['nazwa']:34} {stary['p95_ms']:>11.2f} {nowy['p95_ms']:>11.2f} "
            f"{zmiana:>8.0%}{znacznik}"
        )
    print()
    print(f"Regresji: {regresje}")
    return 1 if regresje else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--scenarios", type=Path, default=Path(__file__).parent / "scenarios.json")
    parser.add_argument("--out", type=Path, help="Gdzie zapisać wynik w JSON")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("PRZED", "PO"))
    args = parser.parse_args()

    if args.compare:
        przed, po = (json.loads(p.read_text(encoding="utf-8")) for p in args.compare)
        return porownaj(przed, po)

    przebieg = uruchom(args.base_url, args.scenarios)
    print()
    print("Zbiór danych:", ", ".join(f"{k}={v}" for k, v in przebieg.zbior.items()))
    niepoprawne = [w for w in przebieg.wyniki if not w.poprawny]
    if niepoprawne:
        print(f"UWAGA: {len(niepoprawne)} scenariuszy zwróciło błąd albo za mało wyników.")
        print("       Czasy z takiego przebiegu nie nadają się do porównań.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(przebieg.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Zapisano: {args.out}")
    return 1 if niepoprawne else 0


if __name__ == "__main__":
    raise SystemExit(main())
