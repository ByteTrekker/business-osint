# ADR-0004: REST z budżetem zapytania zamiast GraphQL i rekurencyjnego CTE

Data: 2026-08-29 · Status: przyjęte

## Kontekst

Trzeba udostępnić eksplorację grafu w sposób, który jest jednocześnie użyteczny
i odporny na eksplozję kosztu. Skrajny przypadek: adres z 5 tys. spółek
(wirtualne biuro) — naiwne rozwinięcie na 3 poziomy zwraca pół bazy.

## Decyzja 1: REST, nie GraphQL

Klient potrzebuje trzech kształtów odpowiedzi (wyszukiwanie, profil, podgraf).
Do trzech kształtów REST jest prostszy, a GraphQL dokłada realne koszty:

* zagnieżdżone zapytanie o dowolnej głębokości to wektor DoS — trzeba dokładać
  analizę złożoności, czyli odtwarzać budżet, który w REST jest parametrem,
* traci się cache HTTP (wszystko to POST na jeden endpoint), a `as_of` daje
  cache za darmo,
* rate limiting per zapytanie traci sens, gdy zapytania różnią się kosztem
  o cztery rzędy wielkości — a to jest wprost problem dla planu B2B.

GraphQL rozważymy jako **dodatkową** warstwę, gdy pojawi się klient B2B
składający własne widoki.

## Decyzja 2: BFS poziom po poziomie, nie rekurencyjny CTE

Traversal jest realizowany jako N zapytań (N = głębokość), nie jednym
`WITH RECURSIVE`.

**Dlaczego:**

* `LIMIT` w członie rekurencyjnym CTE nie ma zdefiniowanej semantyki, a odwołanie
  rekurencyjne wewnątrz podzapytania/LATERAL jest w PostgreSQL zabronione —
  nie da się tam czysto wyrazić limitu rozgałęzień na węzeł;
* przy głębokości ≤ 3 to są maksymalnie 3 round-tripy na indeksach; narzut
  sieciowy jest pomijalny wobec kosztu I/O;
* logika budżetu i przycinania hubów jest testowalna bez bazy
  (`domain/graph_budget.py`, testy jednostkowe w milisekundach);
* plan zapytania jest przewidywalny — jedno `= ANY(:ids)` na indeksie.

Wariant rekurencyjny wróci przy funkcji „najkrótsza ścieżka między X a Y”,
gdzie liczba poziomów jest nieznana z góry.

## Decyzja 3: budżet jest częścią kontraktu API

Każda odpowiedź grafowa zawiera `meta.truncated` i `meta.suppressed_hubs`.
**Ciche przycięcie wyniku w narzędziu do compliance jest defektem krytycznym** —
użytkownik musi wiedzieć, że widzi wycinek.

Pięć warstw ochrony:

1. budżet węzłów (`max_nodes`),
2. limit rozgałęzień na węzeł, egzekwowany **w SQL-u** przez `row_number()`,
3. niepogłębianie hubów (stopień > 150) — węzeł widoczny, ale nierozwijany,
4. domyślne ukrycie relacji wyprowadzonych (tworzą kliki n²),
5. `statement_timeout` = 5 s na połączeniu — ostatnia linia obrony.

## Konsekwencje

* Klient buduje głębokość przez kolejne wywołania `depth=1` na kliknięcie —
  koszt jest proporcjonalny do zainteresowania użytkownika.
* Budżet zależy od planu taryfowego (`GraphBudget.for_plan`), więc monetyzacja
  nie wymaga zmian w warstwie zapytań.
* Interfejs musi wizualnie oznaczać huby i przycięcia — jest to zrobione
  w `RelationshipGraph.tsx` (czerwona przerywana obwódka + komunikat).
