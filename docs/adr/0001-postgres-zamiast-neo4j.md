# ADR-0001: PostgreSQL jako baza grafu zamiast Neo4j

Data: 2026-08-29 · Status: przyjęte

## Kontekst

Produkt jest z natury grafowy: węzły (firmy, osoby, adresy) i krawędzie
(zarząd, udziały, siedziba). Docelowa skala: ~1 mln firm, ~5 mln osób,
~50 mln krawędzi. Główny przypadek użycia to sąsiedztwo do 3 poziomów od
wybranego podmiotu.

Naturalnym odruchem jest sięgnięcie po bazę grafową. Postanowiliśmy sprawdzić,
czy ten odruch jest uzasadniony liczbami.

## Decyzja

Używamy PostgreSQL 17 jako jedynej bazy. Graf jest modelowany relacyjnie:
tabela `entities` (węzły) i `relationships` (krawędzie), traversal realizowany
przez ekspansję poziom po poziomie z limitami.

## Uzasadnienie

1. **Skala nie wymaga bazy grafowej.** 50 mln krawędzi to ~6–8 GB z indeksami.
   Ekspansja do 2 poziomów z limitem 25 krawędzi na węzeł to 2 index scany po
   kilkuset wierszach. Przewaga index-free adjacency ujawnia się przy głębokości
   5+, której nasz produkt nie potrzebuje.
2. **Neo4j nie rozwiązuje naszych rzeczywistych problemów.** Trudne w tym
   projekcie są: entity resolution, bitemporalność i provenance. Neo4j nie
   pomaga w żadnym z nich, a bitemporalność wymaga tam ręcznego modelowania
   na właściwościach relacji.
3. **Jedna baza = jedno źródło prawdy.** Wariant „Postgres + Neo4j” wymaga
   synchronizacji i podwaja ryzyko niespójności.
4. **Postgres daje transakcyjność, ograniczenia integralności, JSONB, trigramy
   i partycjonowanie** — wszystko potrzebne, w jednym systemie.

## Konsekwencje

**Pozytywne:** jeden system do utrzymania, transakcyjny ETL, tanie operacje,
łatwy backup i repliki.

**Negatywne:** traversal głębszy niż 3–4 poziomy będzie wymagał optymalizacji;
najkrótsza ścieżka między odległymi węzłami i analizy globalne (centralność)
muszą być liczone offline.

**Mitygacja:** cała logika grafowa jest zamknięta w `repositories/graph.py` za
interfejsem `neighborhood()`. Podmiana implementacji nie dotyka reszty aplikacji.

## Warunki rewizji

Wracamy do tej decyzji, gdy zajdzie **którykolwiek** z warunków:

* p95 dla `/graph/{id}?depth=2` przekroczy 300 ms mimo cache i indeksów,
* pojawi się produktowa potrzeba „znajdź ścieżkę między X a Y” o nieznanej długości,
* liczba krawędzi przekroczy 200 mln.

Wtedy kolejność kroków jest następująca:
1. **Apache AGE** (rozszerzenie grafowe do Postgresa) — te same dane, Cypher,
   zero synchronizacji. Pierwszy wybór.
2. Neo4j jako **indeks do traversalu odbudowywalny z Postgresa** — nigdy jako
   jedyne miejsce, w którym dane istnieją.
