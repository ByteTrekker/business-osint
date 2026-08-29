# Ocena projektu i odpowiedzi na pytania projektowe

Dokument powstał jako odpowiedź na 20 pytań o architekturę. Zawiera też ocenę
samego pomysłu, bo część ryzyk tego projektu nie jest techniczna.

## Ocena pomysłu — krótko

**Pomysł jest dobry i wykonalny.** Wyróżnik („graf, nie wyszukiwarka”) jest
prawdziwy, a nie marketingowy: KRS udostępnia dokumenty, nie relacje. Zbudowanie
warstwy relacyjnej ponad rejestrami to realna wartość dodana.

**Trzy rzeczy, które zdecydują o powodzeniu — i żadna z nich nie jest bazą danych:**

1. **Entity resolution.** To jest cały produkt. Jeżeli Jan Kowalski z Firmy A
   i Jan Kowalski z Firmy B to ta sama osoba tylko czasem, graf jest bezwartościowy
   albo — gorzej — wprowadza w błąd w procesie due diligence.
2. **Dostęp do danych.** API KRS jest publiczne, ale bez SLA i bez bulk exportu.
   Pobranie 700 tys. podmiotów po jednym odpisie na sekundę zajmuje ~8 dni.
   To ograniczenie definiuje harmonogram, nie stack.
3. **Prawo.** Publikujesz dane osobowe (imię, nazwisko, powiązania) w formie
   ułatwiającej profilowanie. Podstawą jest art. 6 ust. 1 lit. f RODO, ale
   wymaga to procedury sprostowań i informacji o źródle. Konkurenci
   (Rejestr.io, Aleo, KRS-Online) tę procedurę mają. Patrz [03-prawo-i-ryzyko.md](03-prawo-i-ryzyko.md).

**Konkurencja istnieje** (Rejestr.io ma dokładnie ten produkt). To nie jest
argument przeciw — jest argument za tym, żeby wyróżnik był ostrzejszy niż
„to samo, ale moje”. Najciekawsze nisze: powiązania **historyczne** w czasie
(„kto był w zarządzie w dniu podpisania umowy”), łączenie z **zamówieniami
publicznymi i dotacjami** oraz **monitoring zmian** z alertami.

---

## 1. PostgreSQL czy Neo4j na MVP?

**PostgreSQL. Zdecydowanie.** I to nie jest kompromis — to jest właściwy wybór.

Uzasadnienie liczbowe: 50 mln krawędzi w tabeli `relationships` to ok. 6–8 GB
z indeksami. Zapytanie „sąsiedztwo do 2 poziomów z limitem 25 krawędzi na węzeł”
to 2 index scany po ~600 wierszy. Na SSD z ciepłym cache — jednostki milisekund.
Neo4j wygrywa dopiero przy traversalach o głębokości 5+ i przy szukaniu
najkrótszej ścieżki między odległymi węzłami, bo tam koszt joinów rośnie
wykładniczo, a index-free adjacency przestaje być marketingiem.

Dodatkowo Neo4j **nie rozwiązuje** żadnego z trzech faktycznych problemów tego
projektu: entity resolution, bitemporalności i provenance. W Neo4j
bitemporalność trzeba modelować ręcznie na właściwościach relacji, a ograniczenia
integralności są słabsze niż w Postgresie. Wprowadzenie Neo4j na MVP oznacza:
dwie bazy do synchronizacji, dwa modele do utrzymania i podwojone ryzyko
niespójności — w zamian za wydajność, której na tym etapie nie potrzebujesz.

**Warunki, przy których wracamy do tematu** (zapisane w ADR-0001):
p95 zapytania o graf > 300 ms dla depth 2 **albo** pojawi się produktowa potrzeba
„znajdź ścieżkę między X a Y" o nieznanej długości. Wtedy właściwym krokiem jest
najpierw Apache AGE (rozszerzenie grafowe do Postgresa — te same dane, język
Cypher, zero synchronizacji), a Neo4j dopiero gdy AGE nie wystarczy.

## 2. Czy stack FastAPI + PostgreSQL + Next.js + Cytoscape.js jest sensowny?

**Tak, to trafny wybór dla każdego elementu.** Uwagi:

* **FastAPI** — dobry wybór. Automatyczny OpenAPI ma tu konkretną wartość
  biznesową: API B2B z waszego planu monetyzacji dostaje dokumentację i klientów
  SDK za darmo.
* **SQLAlchemy 2 async** — użyteczne, ale pilnujcie jednej rzeczy: zapytania
  grafowe piszcie surowym SQL-em przez `text()`, nie ORM-em. ORM służy do zapisu
  (ETL), Core/SQL do odczytu grafu. Mieszanie tego kończy się N+1 i lazy loadingiem
  w pętli traversalu.
* **Cytoscape.js zamiast React Flow** — słuszne i z właściwego powodu. Cytoscape
  ma layouty grafowe (fcose, cola, dagre), algorytmy grafowe po stronie klienta
  (betweenness, komponenty spójne) i radzi sobie z ~2–5 tys. węzłów. React Flow
  jest do diagramów rysowanych ręcznie i nie ma layoutów siłowych z pudełka.
* **Next.js** — bardziej niż potrzeba na MVP, ale opłaca się z powodu SEO:
  profil każdej spółki wyrenderowany serwerowo to darmowy kanał pozyskania
  użytkowników. Rejestr.io ma z tego większość ruchu. To jedyny powód, dla
  którego nie wystarczy Vite + React SPA — i jest to powód wystarczający.

Czego brakuje w stacku — patrz pytanie 18.

## 3. Jak zaprojektować model, żeby migracja do Neo4j była łatwa?

Nie projektujcie „pod Neo4j”. Projektujcie **pod graf**, a to daje przenośność
za darmo. Konkretnie trzy zasady, których trzymamy się w tym repo:

1. **Jedna tabela węzłów** (`entities`) dla wszystkich typów. Każdy węzeł ma
   niezmienny UUID, który przeżyje migrację i będzie kluczem w Neo4j.
2. **Jedna tabela krawędzi** (`relationships`) z `(source_entity_id,
   target_entity_id, relationship_type)`. To jest dosłownie format eksportu do
   `LOAD CSV` / `neo4j-admin import`.
3. **Zero logiki grafowej w SQL-u rozsianym po kodzie.** Cały traversal jest
   w `repositories/graph.py`, za interfejsem `neighborhood()`. Migracja to
   podmiana jednej klasy, nie przepisywanie aplikacji.

Eksport do Neo4j sprowadza się wtedy do dwóch zapytań:

```sql
COPY (SELECT id, entity_type, display_name FROM entities WHERE merged_into_id IS NULL)
  TO '/tmp/nodes.csv' CSV HEADER;
COPY (SELECT source_entity_id, target_entity_id, relationship_type, valid_from, valid_to
      FROM relationships WHERE superseded_at IS NULL)
  TO '/tmp/edges.csv' CSV HEADER;
```

Uwaga praktyczna: przy migracji nie przenoście do Neo4j **wszystkiego**.
Właściwy docelowy podział to Postgres jako system źródłowy (prawda, historia,
provenance, transakcje) + Neo4j jako indeks do traversalu, odbudowywalny w całości
z Postgresa. Neo4j nigdy nie powinien być jedynym miejscem, gdzie coś istnieje.

## 4. Generyczne „entities + relationships” czy osobne tabele?

**Hybryda — i to jest istotna decyzja, nie kompromis.**

* `entities` — wspólna tabela **tożsamości i grafu**: id, typ, nazwa
  wyświetlana, nazwa znormalizowana, stopień węzła, wskaźnik scalenia.
* `companies` / `people` / `addresses` — tabele **atrybutów**, relacja 1:1
  z `entities` (PK = FK).

Dlaczego nie czysty EAV (wszystko w jednej tabeli z `attributes jsonb`): tracicie
typy, `NOT NULL`, klucze obce i sensowne indeksy. Zapytanie „spółki z kapitałem
> 1 mln zarejestrowane po 2020” staje się rzeźbieniem w JSON-ie.

Dlaczego nie osobne tabele bez wspólnych `entities`: `relationships` musiałoby
mieć polimorficzne FK (`source_type` + `source_id` bez integralności referencyjnej),
a każdy traversal to `UNION` po wszystkich typach. Dodanie nowego typu węzła
(fundacja, spółka zagraniczna, przetarg) oznaczałoby zmianę wszystkich zapytań
grafowych. Przy planowanym rozszerzaniu o przetargi i dotacje to zabójcze.

Hybryda daje: integralność, typowanie, jeden traversal dla wszystkich typów
i tanie dodawanie nowych typów węzłów. Koszt: jeden JOIN przy odczycie profilu —
nieistotny, bo profil to jeden wiersz.

## 5. Jak przechowywać historię relacji?

**Bitemporalnie.** To jedyne poprawne rozwiązanie i jednocześnie najmocniejszy
wyróżnik produktu. Dwie niezależne osie czasu:

| oś | kolumny | odpowiada na pytanie |
|---|---|---|
| czas rzeczywisty (*valid time*) | `valid_from`, `valid_to` | kiedy fakt obowiązywał |
| czas systemowy (*transaction time*) | `recorded_at`, `superseded_at` | kiedy **my** o nim wiedzieliśmy |

Przykład z pytania — „Jan Kowalski był członkiem zarządu firmy X od 2020 do 2023”:

```sql
INSERT INTO relationships
  (source_entity_id, target_entity_id, relationship_type, role,
   valid_from, valid_to, recorded_at)
VALUES
  (:jan, :firma_x, 'board_member_of', 'CZŁONEK ZARZĄDU',
   '2020-02-01', '2023-06-30', now());
```

Stan na dowolny dzień to zwykły `WHERE`:

```sql
WHERE (valid_from IS NULL OR valid_from <= :as_of)
  AND (valid_to   IS NULL OR valid_to   >= :as_of)
  AND superseded_at IS NULL
```

**Nigdy nie robimy `UPDATE` na fakcie i nigdy `DELETE`.** Zmiana = zamknięcie
starego wiersza (`superseded_at = now()`) i wstawienie nowego. Dzięki temu da się
odpowiedzieć na pytanie, które w due diligence jest kluczowe: *„co pokazywał
wasz serwis 3 marca, kiedy podpisywaliśmy umowę?”* — i obronić się, gdy rejestr
zmieni dane wstecz.

Dwie pułapki, na które trzeba uważać:

* KRS **nie zawsze podaje datę wykreślenia**. Gdy powiązanie znika z odpisu bez
  daty, zamykamy je datą naszego importu i oznaczamy w `attributes`, że data jest
  przybliżona (`{"valid_to_inferred": true}`). Zgadywanie bez oznaczenia to
  produkowanie fałszywych faktów.
* Odpis **aktualny** nie zawiera historii — trzeba pobierać odpis **pełny**.

## 6. Entity resolution — imiennicy, zmiana nazwiska, warianty nazw firm

To jest najtrudniejszy problem w projekcie i jedyny, którego nie da się „dodać
później”. Kolejność jest zawsze taka sama: **deterministycznie, potem heurystycznie,
a przy wątpliwości — do kolejki, nie do bazy.**

**Firmy — problem prawie rozwiązany.** KRS/NIP/REGON są unikalne i mają sumy
kontrolne. Tabela `entity_identifiers` z `UNIQUE(scheme, value)` załatwia 95%
przypadków. Warianty nazwy („ALFA Sp. z o.o.” vs „ALFA SPÓŁKA Z OGRANICZONĄ
ODPOWIEDZIALNOŚCIĄ”) rozwiązuje normalizacja formy prawnej
(`domain/normalization.py`) — mamy na to testy.

**Osoby — problem otwarty i trzeba go traktować z pokorą.** W KRS przy osobach
fizycznych **nie ma PESEL-u w danych publicznych**. Zostaje imię, nazwisko
i czasem imiona rodziców. W Polsce jest ~140 tys. Nowaków. Dlatego:

* Zgodność imienia i nazwiska **nigdy** nie daje automatycznego scalenia.
  W kodzie: `test_identical_names_alone_never_auto_merge_people`.
* Scalamy dopiero przy dodatkowym sygnale: ten sam adres, ta sama druga spółka,
  rocznik, ciągłość czasowa ról.
* Wynik pośredni (0.75–0.92) idzie do **kolejki przeglądu**, nie do bazy.
* Każde scalenie jest zapisane w `entity_merges` i **odwracalne**. To nie jest
  luksus: pierwsza reklamacja od osoby błędnie powiązanej ze spółką-wydmuszką
  przyjdzie w ciągu miesiąca od startu.

**Zmiana nazwiska** — `people.former_names` (JSONB z datą i źródłem). Sygnałem
jest ten sam rocznik + ta sama spółka + ciągłość czasowa („Kowalska do 2021,
Nowak od 2021 w tym samym zarządzie”). To jest przypadek dla kolejki przeglądu,
nie dla automatu.

**Błędy w danych źródłowych** — nie poprawiamy ich w miejscu. Surowy dokument
zostaje niezmieniony w `raw_documents`, a korekta jest osobnym faktem z własnym
źródłem (`source = manual`) i wyższym priorytetem. Dzięki temu ponowny import
z rejestru nie kasuje ręcznej poprawki i widać, kto ją wprowadził.

**Strategia budowania:** blocking (klucz z `normalization.py`) → scoring cech →
próg. To wystarczy do ~5 mln osób. Uczenie maszynowe (np. Splink / Fellegi-Sunter)
ma sens dopiero wtedy, gdy będziecie mieli kilka tysięcy ręcznie ocenionych par
z kolejki przeglądu — czyli po roku działania, nie na MVP.

## 7. Czy Polars nadaje się do ETL?

**Tak, ale nie do tego, do czego prawdopodobnie chcecie go użyć.**

Polars jest znakomity do: masowych plików (paczki REGON/CEIDG w CSV mają setki
MB), joinów w pamięci przy deduplikacji, przetwarzania kolumnowego. Będzie
wyraźnie szybszy niż pandas i ma znacznie lepsze API.

Polars **nie nadaje się** do przetwarzania zagnieżdżonych JSON-ów z API KRS —
odpis to głęboko zagnieżdżone drzewo, nie tabela. Do tego jest zwykły Python
i mapper (`etl/sources/krs_mapper.py`), który jest czystą funkcją i ma testy na
zamrożonym fixture.

Podział, który polecam:

| zadanie | narzędzie |
|---|---|
| pobieranie z API | `httpx` + limiter |
| parsowanie odpisu KRS (JSON) | czysty Python, mapper z testami |
| import paczek REGON/CEIDG (CSV) | **Polars** |
| deduplikacja / blocking na milionach rekordów | **Polars** lub SQL |
| zapis do bazy | SQLAlchemy Core `insert().on_conflict_do_nothing()` lub `COPY` |

Nie dodawajcie Polarsa na start — dopiero przy pierwszym imporcie paczki REGON.
To jest zależność, która zarabia na siebie w tygodniu 4, nie w tygodniu 1.

## 8. Event-driven ingestion czy batch?

**Batch. Bez wahania.** Rejestry aktualizują się raz na dobę i **nie mają
webhooków** — nie ma zdarzeń, na które można reagować. Event-driven ingestion
bez źródła zdarzeń to kolejka, w której sami produkujecie własne wiadomości,
żeby samemu je skonsumować. To narzut, nie architektura.

Właściwa ścieżka rozwoju:

1. **Teraz:** funkcja Pythona uruchamiana z crona/APScheduler. Stan przebiegu
   w tabeli `ingestion_runs` — to wystarczy do wznawiania i debugowania.
2. **Gdy import przestanie mieścić się w oknie nocnym:** pula workerów
   z kolejką zadań w Postgresie (`SELECT ... FOR UPDATE SKIP LOCKED`). To
   dosłownie 100 linii kodu i zero nowej infrastruktury.
3. **Gdy zadania staną się różnorodne (alerty, eksporty, ponowne przeliczenia):**
   Redis + arq/Celery.
4. **Kafka:** kiedy będziecie mieli konsumentów, których nie kontrolujecie.
   Prawdopodobnie nigdy.

Jedna rzecz, którą warto zrobić od początku, bo później jest droga: **zdarzenia
domenowe wewnątrz aplikacji**. Zapisujcie do tabeli `entity_changes` fakt
„relacja X powstała/zniknęła” w tej samej transakcji, co zmiana. To jest
fundament pod płatną funkcję alertów i pod audyt — a dopisanie tego wstecz
oznacza utratę historii.

## 9. Provenance — skąd wiemy, że ta relacja istnieje?

Model w tym repo (`db/models.py`) realizuje to trzema poziomami:

```
relationships ──< relationship_sources >── raw_documents ──> sources
   (fakt)          (locator: gdzie          (surowy JSON      (rejestr,
                    dokładnie w dok.)        + sha256 + data)   licencja)
```

Zasady, które to czynią wiarygodnym:

* **`raw_documents` jest niezmienne.** Zapisujemy surową odpowiedź rejestru
  **zanim** ją sparsujemy, razem z `content_sha256` i `fetched_at`. Bez tego
  nie da się odtworzyć, dlaczego parser wyprodukował dany wynik.
* **`locator`** wskazuje konkretne miejsce w dokumencie (JSON Pointer, np.
  `/odpis/dane/dzial2/reprezentacja/sklad/0`). „Źródło: KRS” to za mało w produkcie
  do due diligence — użytkownik musi móc zweryfikować konkretny wpis.
* **Relacja może mieć wiele źródeł.** KRS i CRBR potwierdzające ten sam fakt to
  dwa wiersze w `relationship_sources` i wyższa pewność.
* **`confidence`** rozróżnia fakt z rejestru od wywnioskowanego przez nas
  („te dwie spółki mają wspólnego prezesa”). Relacje wyprowadzone są domyślnie
  ukryte w API — bo to nasza interpretacja, nie dane urzędowe.
* Deduplikacja snapshotów po `content_sha256`: codzienny crawl 1 mln podmiotów
  nie tworzy 1 mln nowych wierszy dziennie, tylko tyle, ile faktycznie się zmieniło.

To jest funkcja, którą widzi użytkownik — w interfejsie każdy wiersz w tabeli
powiązań ma kolumnę „źródło” z linkiem i datą pobrania.

## 10. Największe problemy przy 1 mln firm / kilku mln osób / kilkudziesięciu mln relacji

Uporządkowane według tego, co faktycznie zaboli, a nie co brzmi groźnie:

1. **Huby.** To jest problem numer jeden i nie jest to problem wydajności bazy,
   tylko projektu produktu. Wirtualne biuro z 5 tys. spółek pod jednym adresem,
   syndyk w 300 spółkach, Skarb Państwa jako udziałowiec. Naiwny BFS depth 3
   z takiego węzła zwraca pół bazy. Rozwiązanie w kodzie: `domain/graph_budget.py`
   — twardy limit węzłów, limit rozgałęzień na węzeł i **niepogłębianie hubów**
   (węzeł o stopniu > 150 pokazujemy, ale go nie rozwijamy).
2. **Entity resolution na skali.** Porównanie „każdy z każdym” dla 5 mln osób to
   12,5 biliona par. Bez blokowania (blocking) to jest niewykonalne — a z blokowaniem
   po kluczu `imię|nazwisko|rocznik` schodzi do wykonalnych zbiorów. Ten problem
   rośnie kwadratowo, więc trzeba go rozwiązać **zanim** baza urośnie.
3. **Czas pełnego importu.** ~1 req/s do API KRS × 700 tys. podmiotów ≈ 8 dni
   ciągłego pobierania. To determinuje harmonogram projektu. Import musi być
   wznawialny (stan w `ingestion_runs`) i przyrostowy.
4. **Rozmiar `raw_documents`.** Odpis pełny to 50–500 KB JSON-a. 1 mln podmiotów
   × historia = szybko setki GB. Rozwiązanie: JSONB tylko dla świeżych snapshotów,
   starsze do obiektowego storage (S3/MinIO), w bazie zostaje hash i `storage_uri`.
   Plus partycjonowanie `raw_documents` po miesiącach.
5. **Rozjazd cache'u przy zmianie danych.** Profil spółki jest cache'owany, ale
   po nocnym imporcie 50 tys. profili trzeba unieważnić. Rozwiązanie: klucz cache
   zawiera `entities.updated_at`, więc unieważnienie jest naturalne.
6. **Bloat tabeli `relationships`.** Bitemporalność oznacza, że wiersze tylko
   przybywają. Przy 50 mln aktywnych krawędzi i kilkuletniej historii — 200 mln+
   wierszy. Rozwiązanie: indeksy częściowe `WHERE superseded_at IS NULL` (są
   w migracji) oraz partycjonowanie po `superseded_at IS NULL` gdy przekroczycie
   ~100 mln wierszy.

Czego **nie** ma na tej liście, a często się o to martwi: rozmiar bazy (kilkadziesiąt
GB to dla Postgresa nic) i liczba zapytań (to jest read-heavy workload, idealny
pod repliki i cache).

## 11. Czy PostgreSQL wystarczy do grafu 1–3 poziomy przy tej skali?

**Tak, z zapasem — pod warunkiem trzech rzeczy**, które są zaimplementowane:

1. Dwa indeksy częściowe `(source_entity_id, ...)` i `(target_entity_id, ...)`
   z `INCLUDE`, filtrowane po `superseded_at IS NULL`. Dają index-only scan.
2. Limit rozgałęzień na węzeł (`fanout_per_node`) i globalny budżet węzłów.
   Bez tego jedno kliknięcie w hub generuje zapytanie na miliony wierszy.
3. Ekspansja poziom po poziomie z parametrem `= ANY(:ids)` zamiast jednego
   rekurencyjnego CTE — ma przewidywalny plan i pozwala egzekwować budżet.

Szacunek dla depth 2 z fanout 25: poziom 1 to ~25 krawędzi, poziom 2 to ~625.
Dwa index scany po kilkuset wierszach każdy. To jest kilka milisekund, nie setki.

Gdzie Postgres faktycznie przegra: **najkrótsza ścieżka między dwoma dowolnymi
podmiotami** o nieznanej długości i **analizy globalne** (centralność, wykrywanie
społeczności na całym grafie). To są zadania offline — liczone w nocy do tabeli
wynikowej, albo w Apache AGE, albo w `igraph` na wyeksportowanym grafie.

## 12. Jak zaprojektować API do eksploracji grafu?

Zasada nadrzędna: **API nie zwraca „grafu”, tylko sąsiedztwo w budżecie.**
Głębokość eksploracji buduje klient przez kolejne wywołania, nie serwer przez
jedno wielkie zapytanie.

```
GET /api/v1/search?q=alfa
GET /api/v1/entities/{id}                      → profil
GET /api/v1/entities/{id}/relationships        → płaska lista + provenance
GET /api/v1/graph/{id}?depth=2&as_of=2022-01-01&types=board_member_of
        → { nodes[], edges[], meta: { truncated, suppressed_hubs, node_count } }
```

Cztery decyzje, które warto skopiować:

* **`meta.truncated` jest obowiązkowe.** Użytkownik due diligence musi wiedzieć,
  że widzi wycinek. Ciche przycięcie wyniku w narzędziu do compliance to defekt
  krytyczny, nie kosmetyczny.
* **Format `{nodes, edges}`** — wprost do `cy.add()`. Bez transformacji po
  stronie klienta.
* **Eksploracja przez `depth=1` na kliknięcie**, nie przez `depth=5` na starcie.
  Koszt jest wtedy proporcjonalny do zainteresowania użytkownika.
* **`as_of` jako parametr pierwszej klasy** — podgraf historyczny jest
  niezmienny, więc można go cache'ować na dobę (`Cache-Control: max-age=86400`).
  To jest darmowa optymalizacja wynikająca wprost z modelu bitemporalnego.

Później: `GET /graph/path?from=X&to=Y` (najkrótsza ścieżka — najmocniejsza
funkcja dziennikarska), `POST /graph/expand` z listą węzłów (batch), eksport
do CSV/GraphML dla planu Pro.

## 13. REST czy GraphQL?

**REST.** GraphQL nie daje tu przewagi, a dokłada koszty.

Argument „graf danych = GraphQL” jest myleniem nazwy z problemem. GraphQL
rozwiązuje problem *klienta, który potrzebuje różnych kształtów odpowiedzi*.
Wasz klient potrzebuje dokładnie trzech kształtów: wynik wyszukiwania, profil,
podgraf. Do trzech kształtów REST jest prostszy.

Konkretne koszty GraphQL w tym projekcie:

* **Traversal o dowolnej głębokości przez zagnieżdżone zapytanie**
  (`company { people { companies { people { ... } } } }`) to zaproszenie do
  ataku DoS. Trzeba dokładać analizę złożoności zapytania i limity głębokości —
  czyli odtwarzać budżet, który w REST jest jednym parametrem.
* Cache'owanie HTTP przestaje działać (wszystko to POST na jeden endpoint),
  a `as_of` daje wam cache za darmo.
* Rate limiting per zapytanie traci sens, gdy jedno zapytanie może kosztować
  1 ms albo 30 s. To akurat wprost uderza w model B2B.

GraphQL rozważcie, gdy pojawi się klient B2B, który chce sam składać widoki —
i wtedy jako **dodatkową** warstwę nad tym samym API, nie zamiast.

## 14. Jak zabezpieczyć się przed eksplozją grafu?

Pięć warstw, wszystkie zaimplementowane lub przygotowane:

1. **Budżet węzłów** — twardy limit `max_nodes` na odpowiedź. Po jego wyczerpaniu
   `meta.truncated = true`.
2. **Limit rozgałęzień** — `row_number() OVER (PARTITION BY from_id) <= fanout`
   w SQL-u. Ograniczenie dzieje się **w bazie**, nie po pobraniu miliona wierszy.
3. **Niepogłębianie hubów** — węzeł o stopniu > 150 jest pokazany, ale
   nierozwijany. Użytkownik widzi go z adnotacją i może rozwinąć świadomie.
   `entities.degree` jest zdenormalizowany, żeby nie liczyć `COUNT(*)` w traversalu.
4. **Domyślne ukrycie relacji wyprowadzonych** — „wspólny adres” tworzy kliki
   o rozmiarze n², które zabijają zarówno bazę, jak i czytelność wizualizacji.
5. **`statement_timeout` na połączeniu** (5 s) — ostatnia linia obrony.
   Zapytanie ma umrzeć w bazie, nie zająć workera na minutę.

Warstwa produktowa: limity zależą od planu (`GraphBudget.for_plan`). To nie jest
tylko monetyzacja — to jest naturalne miejsce na ograniczenie kosztu ruchu
anonimowego i botów.

## 15. Najważniejsze indeksy PostgreSQL

W kolejności ważności (wszystkie w `alembic/versions/0001_initial_schema.py`):

```sql
-- 1. Traversal w obie strony. Bez tych dwóch nie ma produktu.
CREATE INDEX ix_relationships_out ON relationships (source_entity_id, relationship_type)
  INCLUDE (target_entity_id, valid_from, valid_to, confidence_score)
  WHERE superseded_at IS NULL;
CREATE INDEX ix_relationships_in  ON relationships (target_entity_id, relationship_type)
  INCLUDE (source_entity_id, valid_from, valid_to, confidence_score)
  WHERE superseded_at IS NULL;

-- 2. Wyszukiwanie po identyfikatorze — wejście do entity resolution.
CREATE UNIQUE INDEX uq_entity_identifiers_scheme_value ON entity_identifiers (scheme, value);

-- 3. Wyszukiwanie rozmyte po nazwie. Bez tego `%` to seq scan po 1 mln wierszy.
CREATE INDEX ix_entities_normalized_name_trgm ON entities USING gin (normalized_name gin_trgm_ops);

-- 4. Idempotencja importu — ten sam odpis wgrany dwa razy nie duplikuje krawędzi.
CREATE UNIQUE INDEX uq_relationships_active ON relationships
  (source_entity_id, target_entity_id, relationship_type, COALESCE(valid_from,'epoch'::date))
  WHERE superseded_at IS NULL;

-- 5. Wykrywanie hubów bez COUNT(*).
CREATE INDEX ix_entities_active ON entities (entity_type, degree DESC) WHERE merged_into_id IS NULL;
```

Trzy uwagi, które robią różnicę:

* **`INCLUDE`** daje index-only scan — cała krawędź jest w indeksie, heap
  nietykany. Przy 50 mln wierszy to jest różnica kilkukrotna.
* **Indeksy częściowe `WHERE superseded_at IS NULL`** — historia to docelowo
  większość wierszy, a prawie nigdy nie jest odpytywana. Indeks częściowy jest
  kilkukrotnie mniejszy i mieści się w RAM.
* **`COALESCE` w kluczu unikalnym** — bez tego `NULL != NULL` przepuszcza
  duplikaty przy relacjach bez daty rozpoczęcia. Klasyczna pułapka.

Czego **nie** indeksować na start: kolumn JSONB (dopiero gdy pojawi się konkretne
zapytanie), `valid_from`/`valid_to` osobno (filtr dat jest zawsze wtórny wobec
filtru po węźle).

## 16. Jak przechowywać snapshoty i historię z rejestrów?

Trzy poziomy, każdy z inną trwałością i innym celem:

| poziom | co | gdzie | retencja |
|---|---|---|---|
| surowy | dokładna odpowiedź API + sha256 + data | `raw_documents` → S3 po 90 dniach | wieczna |
| znormalizowany | encje i relacje bitemporalne | `entities`, `relationships` | wieczna |
| pochodny | agregaty, stopnie węzłów, cache | tabele wynikowe | odtwarzalna |

Reguły:

* **Nie zapisujemy snapshotu, który się nie zmienił** — dedup po `content_sha256`
  (`UNIQUE(source_id, external_id, content_sha256)`). Bez tego codzienny crawl
  rośnie liniowo bez powodu.
* **Poziom pochodny musi być odtwarzalny** z dwóch pierwszych jednym poleceniem.
  Jeśli nie jest, to nie jest cache, tylko druga baza danych.
* **Partycjonowanie `raw_documents` po `fetched_at`** (miesięcznie) — pozwala
  odłączyć stare partycje bez `DELETE` na wielkiej tabeli.
* Duże payloady do obiektowego storage, w bazie hash + `storage_uri`. Postgres
  jest dobry we wszystkim oprócz bycia dyskiem na pliki.

## 17. Czy widzę lepszy stack?

**Nie — dla tego zespołu i tego celu proponowany stack jest właściwy.**
Zmieniłbym w nim trzy rzeczy, wszystkie drobne:

1. **Litestar zamiast FastAPI** — szybszy i ma lepszy DI. Ale FastAPI ma
   nieporównywalnie większy ekosystem i to wygrywa. **Zostajemy przy FastAPI.**
2. **Apache AGE w planach zamiast Neo4j** — to samo Postgres, dodatkowo Cypher.
   Wpisane do ADR-0001 jako pierwszy krok, gdy zabraknie wydajności.
3. **Dodać Meilisearch zamiast rozbudowywać wyszukiwanie w Postgresie** — gdy
   trigram przestanie wystarczać. Meilisearch jest znacznie prostszy operacyjnie
   niż Elasticsearch, a do wyszukiwania nazw firm z literówkami wystarcza w pełni.

Warto natomiast zauważyć, że **profil zawodowy (PHP/Symfony) nie jest tu wadą** —
model danych, bitemporalność, provenance i entity resolution to problemy
niezależne od języka. Python jest wyborem właściwym ze względu na ekosystem
danych, nie ze względu na FastAPI.

## 18. Co jest overengineeringiem, a czego brakuje?

**Overengineering na MVP:**

| element | werdykt |
|---|---|
| Neo4j | tak — rozwiązuje problem, którego nie macie (patrz p. 1) |
| Kafka / event-driven ingestion | tak — nie ma źródła zdarzeń (p. 8) |
| Elasticsearch | tak — `pg_trgm` wystarcza do kilku milionów nazw |
| Redis na start | tak — przy read-heavy z `Cache-Control` wystarczy cache HTTP |
| Kubernetes | tak — jedna maszyna z Docker Compose obsłuży pierwsze 10 tys. użytkowników |
| Osobny worker ETL | prawie — na start wystarczy cron; wydzielić w tygodniu 5 |
| Polars | nie, ale nie na dzień 1 — wchodzi przy imporcie paczek REGON |

**Czego brakuje, a jest potrzebne od początku:**

1. **Kolejka przeglądu dla entity resolution.** Bez niej albo scalacie za agresywnie
   (produkujecie fałszywe powiązania), albo za ostrożnie (graf się rozpada).
2. **Zdarzenia domenowe** (`entity_changes`) — fundament pod alerty i audyt.
   Dopisanie wstecz oznacza utratę historii.
3. **Rate limiting i klucze API.** Wasze dane są cenne i będą scrapowane od
   pierwszego dnia. To nie jest funkcja premium, to podstawowa ochrona kosztów.
4. **Procedura sprostowań i usunięcia danych osobowych** (RODO art. 16/17/21).
   To jest wymóg prawny, nie backlog — patrz [03-prawo-i-ryzyko.md](03-prawo-i-ryzyko.md).
5. **Obserwowalność zapytań grafowych** — metryki `depth`, `node_count`,
   `truncated`, czas. Bez tego nie dowiecie się, że produkt jest wolny; dowiecie
   się, że użytkownicy odeszli.
6. **`statement_timeout`** — jedna linia konfiguracji, która ratuje bazę.

## 19. Rekomendowana architektura: MVP i po skali

**MVP (do ~100 tys. podmiotów, 1–2 tys. użytkowników dziennie)**

```
Next.js ──REST──> FastAPI ──> PostgreSQL 17
                     ▲              ▲
                     └── ETL (cron) ┘
```
Jedna maszyna (4 vCPU / 16 GB), Docker Compose, Caddy jako reverse proxy z TLS.
Koszt: ~30–50 EUR/mies. Backup: `pg_dump` na S3 co noc + WAL archiving.

**Po skali (1 mln podmiotów, 50 mln relacji, ruch B2B)**

```
              CDN (profile SSR, cache 5 min)
                        │
                   Next.js (2×)
                        │
                 FastAPI (3–5×)  ──> Redis (cache podgrafów + rate limit)
                    │        │
      PostgreSQL primary   read replica (2×)  ← tu idą wszystkie odczyty grafu
            ▲
      ETL workers (kolejka w Postgresie: FOR UPDATE SKIP LOCKED)
            │
      S3/MinIO (surowe dokumenty starsze niż 90 dni)
```

Kluczowe zmiany względem MVP, w kolejności wprowadzania:
1. Repliki do odczytu — workload jest w 99% odczytowy, to najtańszy zysk.
2. Redis na podgrafy (klucz: `entity_id + depth + as_of + plan`).
3. Partycjonowanie `raw_documents` i `relationships`.
4. Wydzielenie ETL na osobne maszyny (import nie może konkurować o CPU z API).
5. Apache AGE **tylko jeśli** metryki pokażą, że traversal jest wąskim gardłem.

Zwróćcie uwagę, czego tu nie ma: mikroserwisów. Ten system ma jeden model danych
i jeden zespół — modularny monolit z wyraźnymi granicami modułów (`domain`,
`repositories`, `etl`, `api`) jest właściwą odpowiedzią i pozostanie nią długo.

## 20. Portfolio senior backend / system design + potencjalny SaaS

Te dwa cele są w 80% zbieżne, ale w 20% się rozjeżdżają — i warto wiedzieć gdzie.

**Co dodać, żeby to był mocny projekt portfolio:**

1. **ADR-y z warunkami rewizji.** Nie „wybrałem Postgres”, tylko „wybrałem
   Postgres, oto liczby, oto próg p95 > 300 ms, przy którym decyzję zmieniam”.
   To jest dokładnie ta różnica między seniorem a midem, której szuka się na
   rozmowie. Są w `docs/adr/`.
2. **Benchmark z prawdziwymi liczbami.** Wygenerujcie 1 mln encji i 20 mln
   relacji, zmierzcie p50/p95/p99 dla depth 1/2/3, wklejcie `EXPLAIN (ANALYZE,
   BUFFERS)` do README. To jest najmocniejszy pojedynczy element tego portfolio —
   pokazuje, że twierdzenie „Postgres wystarczy” jest zmierzone, nie wyczytane.
   Szkielet: `ops/bench.sql`.
3. **Testy, które testują decyzje, a nie gettery.** `test_identical_names_alone_never_auto_merge_people`
   mówi o projekcie więcej niż 200 testów CRUD-a.
4. **Rozdział „czego nie zrobiłem i dlaczego”** w README. Świadome pominięcie
   z uzasadnieniem czyta się lepiej niż udawana kompletność.

**Co zmienić, myśląc o SaaS:**

1. **Zawęźcie wyróżnik.** „Baza firm z grafem” konkuruje z Rejestr.io i przegra
   na danych. Wygrywalne nisze: (a) **monitoring i alerty** — „powiadom mnie,
   gdy zmieni się zarząd któregokolwiek z moich 200 kontrahentów”, za to płacą
   działy compliance i faktoring; (b) **powiązania historyczne w czasie** —
   nikt tego dobrze nie robi, a jest niezbędne przy sporach i due diligence;
   (c) **przetargi + dotacje + powiązania** — wykrywanie karuzeli podmiotów
   startujących w tych samych postępowaniach. To jest funkcja, za którą płacą
   dziennikarze śledczy i UZP.
2. **API B2B od początku jako produkt**, nie dodatek. Klucze, limity, wersjonowanie
   (`/api/v1`), OpenAPI. FastAPI daje to prawie za darmo.
3. **Model danych już jest gotowy pod monetyzację** — `GraphBudget.for_plan()`
   przekłada plan taryfowy na głębokość i budżet. Nie trzeba tego przerabiać.
4. **Zbudujcie najpierw jedną branżę pionowo, nie całą Polskę poziomo.**
   Kompletne, świeże i zweryfikowane dane dla 50 tys. spółek z jednej branży są
   warte więcej niż niekompletne dla miliona.
5. **RODO to nie jest ryzyko odłożone.** Pierwsze żądanie usunięcia danych
   przyjdzie w pierwszym miesiącu. Procedura musi istnieć przed startem.

**Jedna rzecz, którą zmieniłbym w kolejności prac:** nie budujcie najpierw
importu całego KRS. Zbudujcie pionowy przekrój na 1000 spółkach — od pobrania,
przez entity resolution, po graf w przeglądarce — i dopiero wtedy skalujcie
w szerz. Import to problem czasu i cierpliwości; entity resolution to problem
projektowy i tam kryje się całe ryzyko.
