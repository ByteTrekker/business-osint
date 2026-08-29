# ADR-0005: Granice modułów jako przygotowanie do specjalizacji językowej

Data: 2026-08-29 · Status: przyjęte

## Kontekst

System wykonuje trzy bardzo różne rodzaje pracy:

| praca | profil |
|---|---|
| obsługa żądań HTTP | I/O-bound na Postgresie, niska złożoność obliczeniowa |
| pobieranie danych z rejestrów | I/O-bound na sieci, długo działający proces, 700 tys. zadań |
| entity resolution | CPU-bound, równoległy, ~10⁸ porównań stringów |

Python jest właściwym wyborem dla pierwszej i akceptowalnym dla drugiej.
Dla trzeciej jest najgorszym możliwym: narzut obiektów, brak wektoryzacji
porównań stringów i GIL uniemożliwiający zrównoleglenie w obrębie procesu.

Jednocześnie przedwczesne wprowadzenie trzech języków do projektu na etapie MVP
to koszt bez pokrycia: potrójne CI, potrójny onboarding i ryzyko rozjazdu logiki
zaimplementowanej dwa razy.

## Decyzja

**Cały system pozostaje w Pythonie do czasu, aż zmierzone progi zostaną
przekroczone.** Jednocześnie **od teraz** obowiązują granice modułów, które
sprawiają, że późniejsze przepisanie komponentu jest wymianą, a nie rewolucją:

* **G1** — crawler komunikuje się z systemem wyłącznie przez Postgresa
  (`ingestion_tasks` → `raw_documents`); zero importów z `business_osint.*`.
* **G2** — entity resolution jest czystą funkcją na poziomie systemu:
  `resolution_candidates` → `entity_merges`; brak stanu poza bazą.
* **G3** — traversal grafu ma jeden interfejs: `GraphRepository.neighborhood()`.
* **G4** — kontrakty jawne: OpenAPI dla HTTP, protobuf dla usług wewnętrznych,
  schemat bazy jako kontrakt danych.

Docelowy podział języków i **progi wyzwalające**:

| komponent | język docelowy | próg |
|---|---|---|
| entity resolution | Rust (PyO3 → samodzielny job) | pełny przebieg ER > 2 h |
| crawler / ingestion | Go | import poza oknem nocnym |
| usługa grafowa (ścieżki, centralność) | Rust | shortest-path wchodzi do produktu |
| API | Python — bez zmian | — |
| ETL: parsowanie, normalizacja | Python — bez zmian | — |

## Uzasadnienie

**Dlaczego Rust do entity resolution.** To jedyny komponent, w którym język jest
faktycznym ograniczeniem, a nie wymówką. Profil — gorąca pętla po parach
z porównywaniem stringów — jest dokładnie tym, w czym różnica między Pythonem
a kodem natywnym wynosi rzędy wielkości, a nie procenty. Ścieżka jest schodkowa
(`rapidfuzz` → PyO3 → samodzielny job), więc każdy krok można wycofać.

**Dlaczego Go do crawlera, a nie Rust.** Crawler jest I/O-bound: przy limicie
~1 req/s do API KRS ogranicza nas rejestr, nie język. Rust nie daje tu przewagi
wydajnościowej, a kosztuje więcej w pisaniu i utrzymaniu. Argumenty za Go są
**operacyjne**, nie wydajnościowe, i tak trzeba je zapisać, żeby nikt nie
uzasadniał tej decyzji później fałszywie:

* jeden statyczny plik wykonywalny (obraz ~15 MB zamiast ~200 MB),
* przewidywalne zużycie pamięci w procesie działającym tygodniami,
* współbieżność bez ceremonii wokół pętli zdarzeń,
* obecność w stacku zespołu — koszt wejścia bliski zeru.

**Dlaczego API zostaje w Pythonie.** Czas odpowiedzi to czas zapytania SQL plus
serializacja. Przepisanie warstwy HTTP na język kompilowany optymalizuje
składnik, który nie jest wąskim gardłem — i jest najczęstszym błędem przy
tego typu decyzjach.

**Dlaczego progi, a nie daty.** Przepisanie uzasadnione datą w harmonogramie
jest przepisaniem uzasadnionym gustem. Próg oparty na metryce jest falsyfikowalny:
albo został przekroczony, albo nie.

## Konsekwencje

**Pozytywne**

* MVP powstaje w jednym języku, z jedną pętlą zwrotną.
* Każdy komponent da się przepisać niezależnie, bez zatrzymywania reszty.
* Równoważność implementacji jest **dowodliwa** — te same dane wejściowe
  w bazie, te same oczekiwane wyjścia.

**Negatywne**

* Granice G1–G2 wymuszają komunikację przez bazę tam, gdzie wywołanie funkcji
  byłoby prostsze. To świadomy koszt: kilka dodatkowych zapisów w zamian za
  wymienialność komponentu.
* Docelowo trzy zestawy narzędzi w CI i trudniejszy onboarding.
* **Logika zaimplementowana dwa razy grozi rozjazdem.** Dotyczy przede wszystkim
  normalizacji nazw, używanej i przez ETL, i przez crawler.

**Mitygacja rozjazdu (obowiązkowa przy pierwszym komponencie w innym języku):**
wspólny zbiór przypadków testowych w formacie niezależnym od języka
(JSON: wejście → oczekiwane wyjście), uruchamiany w CI przeciwko **każdej**
implementacji. Bez tego rozjazd jest kwestią czasu i objawi się cichym rozpadem
grafu, a nie czerwonym testem.

## Warunki rewizji

* Jeżeli po przejściu na `rapidfuzz` przebieg ER zejdzie poniżej 30 min —
  schodek z PyO3 **odpada**, decyzja o Ruście zostaje wycofana.
* Jeżeli okaże się, że wąskim gardłem ER jest zapis do bazy, a nie scoring —
  właściwą odpowiedzią jest `COPY` i partycjonowanie, nie zmiana języka.
* Jeżeli crawler w Pythonie utrzyma opóźnienie < 48 h przy pełnym wolumenie —
  Go nie wchodzi, mimo że jest wygodniejszy operacyjnie.

Każdy z tych warunków wymaga liczby z produkcji, nie oszacowania.
