# Pomiar wydajności

Narzędzie do odpowiadania na jedno pytanie: **czy po zmianie jest szybciej.**

Zmianą może być nowy indeks, przepisanie backendu na Go albo zamiana
PostgreSQL na coś innego. Pomiar ma przetrwać każdą z nich, więc mierzy
**wyłącznie przez kontrakt HTTP** — to jedyna rzecz, która nie zmienia się przy
wymianie technologii pod spodem.

```bash
make bench                  # przebieg i zapis wyniku
make bench-compare PRZED=... PO=...
```

## Co tu jest i dlaczego

| plik | rola |
|---|---|
| `scenarios.json` | scenariusze jako **dane** — trwały artefakt, przeżywa przepisanie kodu |
| `run.py` | runner na samej bibliotece standardowej |
| `results/` | zapisane przebiegi |

Runner nie korzysta z niczego spoza biblioteki standardowej Pythona. Narzędzie
do porównywania technologii nie może samo wymagać instalowania jednej z nich —
`python3 run.py` ma zadziałać na czystym systemie, także takim, na którym tego
projektu w ogóle nie ma.

## Trzy rzeczy, które odróżniają to od licznika czasu

**Percentyle, nie średnia.** Średnia ukrywa ogon, a użytkownik czuje właśnie
ogon. Raportujemy p50, p95 i p99, metodą najbliższej rangi — bez interpolacji,
żeby podana liczba była czasem, który naprawdę zmierzono.

**Liczba wyników obok czasu.** Implementacja zwracająca mniej rekordów wychodzi
na szybszą. To najczęstszy sposób, w jaki benchmark zaczyna kłamać, więc każdy
scenariusz deklaruje minimalną poprawną liczbę wyników, a porównanie traktuje
zmianę tej liczby jako **regresję niezależnie od czasu**.

**Odcisk zbioru danych.** Przed pomiarem pobierany jest `/stats`: liczba encji,
krawędzi i wersja schematu. Porównanie dwóch przebiegów na różnych danych jest
odmawiane, bo różnica czasów mogłaby wynikać z wielkości zbioru, a nie ze zmian
w aplikacji.

## Podmioty wskazujemy numerem rejestrowym, nie identyfikatorem

Scenariusz mówi „spółka o numerze KRS 0000028860", nigdy „encja `a3f2…`".
Identyfikatory są lokalne dla instalacji i zmieniają się przy każdym imporcie;
numer KRS jest ten sam wszędzie i na zawsze. Dzięki temu ten sam plik działa na
cudzej kopii bazy i po przepisaniu aplikacji.

Jeżeli zbiór danych nie zawiera podmiotów, na których oparte są scenariusze,
runner **przerywa z błędem** zamiast mierzyć coś innego.

## Progi wykrywania zmiany są zmierzone, nie wybrane

Zmiana musi przekroczyć **oba** progi: 25% i 3 ms.

Sam próg względny nie działa przy szybkich scenariuszach: na 1,7 ms wahnięcie
planisty systemu o 0,7 ms to „43% regresji". Zmierzone na tym projekcie — dwa
kolejne przebiegi na identycznym kodzie dawały 36% i 43% różnicy, a w
milisekundach było to poniżej jednej.

Rozgrzewka obejmuje **cały zestaw** przed pomiarem czegokolwiek. Bufor bazy
jest wspólny, więc pierwszy przebieg po starcie wychodził systematycznie o
16–44% wolniej od drugiego przy tym samym kodzie.

## Czym to nie jest

**To nie jest test obciążeniowy.** Trzydzieści żądań sekwencyjnie mierzy
opóźnienie pojedynczego użytkownika, nie przepustowość pod obciążeniem. Na
pytanie „ilu użytkowników uniesie" to nie odpowiada i nie należy udawać, że
odpowiada.

**To nie zastępuje `ops/bench.sql`.** Tamten pokazuje plany zapytań PostgreSQL
i jest właściwym narzędziem przy strojeniu indeksów. Przestaje mieć sens
dokładnie wtedy, gdy zmienia się baza — i po to jest ten katalog.
