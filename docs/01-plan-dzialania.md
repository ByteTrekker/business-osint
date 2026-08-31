# Plan działania

Założenie: jedna osoba, ~15 h/tydzień. Każdy tydzień kończy się czymś, co da się
pokazać. Kolejność wynika z jednej zasady: **najpierw pionowy przekrój przez
cały system na małych danych, potem skala.**

## Etap 0 — szkielet (zrobione)

- [x] Model danych: hybryda `entities` + tabele szczegółów
- [x] Bitemporalność (`valid_from/to` + `recorded_at/superseded_at`)
- [x] Provenance (`raw_documents` → `relationship_sources` z lokalizatorem)
- [x] Traversal z budżetem i przycinaniem hubów
- [x] Wyszukiwarka hybrydowa (identyfikator + trigram)
- [x] Mapper KRS z testami na zamrożonym fixture
- [x] Dane demonstracyjne (`make seed`) — aplikacja działa bez dostępu do rejestrów
- [x] Testy jednostkowe bez bazy + integracyjne z Postgresem
- [x] Docker Compose, CI, migracje

## Tydzień 1–2 — pionowy przekrój na prawdziwych danych

Cel: **jedna prawdziwa spółka z KRS widoczna jako graf w przeglądarce.**

- [ ] Zweryfikować faktyczny kształt JSON z `api-krs.ms.gov.pl` i poprawić mapper
      (fixture w `tests/unit/test_krs_mapper.py` zastąpić prawdziwym odpisem)
- [ ] `business-osint ingest-krs 0000030897` → encje, relacje, provenance w bazie
- [ ] Import 1000 spółek z jednego województwa (lista KRS z paczki REGON)
- [ ] Frontend: wyszukiwarka → profil → graf → klikanie w węzły
- [ ] Metryki zapytań grafowych (czas, liczba węzłów, `truncated`)

**Kryterium ukończenia:** wpisuję nazwę spółki, klikam prezesa, widzę jego inne
spółki. Bez zmyślonych danych.

## Tydzień 3–4 — entity resolution

To jest tydzień, który decyduje o jakości produktu.

- [ ] Blocking po kluczach z `domain/normalization.py` na całym zbiorze
- [ ] Scoring par + zapis do tabeli `resolution_candidates`
- [ ] Kolejka przeglądu: prosty UI „ta sama osoba / inna osoba / nie wiem”
- [ ] Zapis decyzji do `entity_merges` (odwracalny)
- [ ] Metryka: ile procent osób ma > 1 spółkę, ile par trafia do przeglądu
- [ ] Test regresji na ręcznie ocenionym zbiorze 200 par

**Kryterium ukończenia:** dwóch różnych Janów Kowalskich pozostaje dwoma węzłami,
a ta sama Anna Nowak w trzech spółkach jest jednym węzłem.

## Tydzień 5–6 — pełny import i MVP publiczne

- [ ] Wznawialny import całego KRS (`ingestion_runs`, przyrostowo, ~8 dni w tle)
- [ ] Import paczki REGON (Polars) — uzupełnienie adresów i PKD
- [ ] Adresy jako węzły + normalizacja adresów (TERYT)
- [ ] Rate limiting + klucze API
- [ ] Strony profili renderowane serwerowo (SEO) + `sitemap.xml`
- [ ] Procedura sprostowań RODO (formularz + rejestr żądań)
- [ ] Deploy: jedna maszyna, Caddy + TLS, backup `pg_dump` na S3

**Kryterium ukończenia MVP:** publiczny adres, na którym da się wyszukać dowolną
polską spółkę i zobaczyć jej graf powiązań ze źródłami.

## Kwartał 2 — to, za co ktoś zapłaci

Kolejność według stosunku wartości do kosztu:

1. **Alerty o zmianach** — tabela `entity_changes` (zapisywana od początku),
   listy obserwowanych, e-mail. Najkrótsza droga do pierwszego przychodu.
2. **CRBR** — beneficjenci rzeczywiści. Dane, których nie ma w KRS, a są
   kluczowe dla compliance i AML.
3. **Historia w czasie** — suwak `as_of` w interfejsie. Model już to obsługuje,
   zostaje UI.
4. **Zamówienia publiczne** (BZP/TED) — wtedy graf odpowiada na pytanie
   „czy te dwie firmy startujące w jednym przetargu są powiązane”.
5. **API B2B** — klucze, limity, plany, dokumentacja z OpenAPI.
6. **Eksport** (CSV/GraphML/PDF) — plan Pro.

## Kwartał 3+ — skala i pogłębienie

- Dotacje UE, sprawozdania finansowe (eKRS), CEIDG
- Scoring ryzyka (spółki-wydmuszki, karuzele podmiotów, wspólne adresy)
- Najkrótsza ścieżka między podmiotami (funkcja dla dziennikarzy)
- Repliki do odczytu + Redis, partycjonowanie
- Apache AGE — **tylko jeśli** metryki pokażą, że traversal jest wąskim gardłem

## Etap 4 — specjalizacja językowa (kwartał 3+)

Pełna analiza: [05-strategia-wielojezykowa.md](05-strategia-wielojezykowa.md)
i [ADR-0005](adr/0005-granice-i-specjalizacja-jezykowa.md).

Zasada: komponent przepisujemy, gdy **zmierzony** próg zostanie przekroczony —
nie według daty w harmonogramie.

**Do zrobienia od razu (koszt bliski zeru, umożliwia wszystko poniżej):**

- [ ] tabela `ingestion_tasks` + pobieranie zadań przez `FOR UPDATE SKIP LOCKED`
- [ ] granica G1: crawler rozmawia z systemem wyłącznie przez Postgresa
- [ ] granica G2: ER jako `resolution_candidates` → `entity_merges`
- [ ] wspólny zbiór testów kontraktowych normalizacji (JSON: wejście → wyjście),
      niezależny od języka implementacji

**Wyzwalane progiem:**

| komponent | język | próg | schodek pośredni |
|---|---|---|---|
| entity resolution | Rust | przebieg ER > 2 h | najpierw `rapidfuzz` + PyO3 |
| crawler / ingestion | Go | import poza oknem nocnym | — |
| usługa grafowa (ścieżki, centralność) | Rust | shortest-path wchodzi do produktu | najpierw Apache AGE |
| API | **zostaje Python** | — | — |

Reguła twarda: **żadne przepisanie nie startuje bez benchmarku „przed"
w repozytorium.** Bez punktu odniesienia nie da się wykazać, że przepisanie
cokolwiek dało.

## Czego świadomie nie robimy i dlaczego

| pomijamy | powód |
|---|---|
| Neo4j | brak problemu do rozwiązania — patrz ADR-0001 |
| Kafka | brak źródła zdarzeń, rejestry nie mają webhooków |
| Kubernetes | jedna maszyna obsłuży pierwsze 10 tys. użytkowników |
| Mikroserwisy | jeden model danych, jeden zespół |
| Elasticsearch | `pg_trgm` wystarcza do kilku milionów nazw |
| Scraping komercyjnych agregatorów | ryzyko prawne i uzależnienie od cudzego produktu |
| ML do entity resolution | brak danych treningowych; reguły + kolejka przeglądu wystarczą na start |
| przepisanie na Rust/Go teraz | brak zmierzonego wąskiego gardła — patrz ADR-0005 |

## Wskaźniki, które warto mierzyć od pierwszego dnia

| wskaźnik | próg alarmowy |
|---|---|
| p95 czasu `/graph/{id}?depth=2` | > 300 ms → czas na cache lub AGE |
| odsetek odpowiedzi z `truncated=true` | > 20% → budżety są za ciasne albo huby źle obsłużone |
| liczba par w kolejce przeglądu | rośnie szybciej niż jest rozpatrywana → progi za luźne |
| opóźnienie danych względem rejestru | > 48 h → import nie nadąża |
| odsetek relacji bez provenance | > 0 → błąd w loaderze, nie do zaakceptowania |
