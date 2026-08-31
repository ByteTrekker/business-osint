# Strategia wielojęzykowa

Dokument opisuje, **które komponenty i kiedy** przechodzą z Pythona na inny
język, oraz co trzeba zrobić dzisiaj, żeby to przejście było wymianą klocka,
a nie przepisywaniem systemu.

## Zasada nadrzędna

> Komponent przepisujemy, gdy **zmierzony** profil obciążenia wskazuje na
> ograniczenie języka, a nie implementacji.

Kolejność jest zawsze taka sama i nie wolno jej skracać:

1. **Zmierz.** Profil (`py-spy`, `EXPLAIN ANALYZE`, metryki z produkcji).
2. **Sprawdź, czy problem jest w bazie.** W 80% przypadków jest — brakujący
   indeks bije każdy język.
3. **Zoptymalizuj w Pythonie.** Biblioteki natywne (`polars`, `rapidfuzz`,
   `orjson`) to często ten sam rząd wielkości co przepisanie, przy zerowym
   koszcie operacyjnym.
4. **Dopiero teraz zmień język** — i tylko dla tego jednego komponentu.

Przepisanie bez benchmarku „przed” w repozytorium jest zabronione. Nie z powodu
formalności: bez punktu odniesienia nie da się wykazać, że przepisanie cokolwiek
dało, a to jest jedyny sposób, żeby taka decyzja nie była kwestią gustu.

## Co trzeba zrobić dzisiaj

Przepisanie komponentu jest tanie tylko wtedy, gdy granice zostały ustanowione
zawczasu. Cztery granice, które obowiązują **od teraz**:

### G1. Crawler rozmawia z systemem wyłącznie przez Postgresa

Wejście: kolejka zadań (`ingestion_tasks`, pobierana przez
`SELECT ... FOR UPDATE SKIP LOCKED`). Wyjście: wiersze w `raw_documents`.
Zero współdzielonego kodu z API, zero importów z `business_osint.*`.

Konsekwencja: crawler w dowolnym języku, który umie w Postgresa, jest wymienny
bez zmian w reszcie systemu.

### G2. Entity resolution jest czystą funkcją na poziomie systemu

Wejście: `resolution_candidates` (pary do oceny wygenerowane przez blocking).
Wyjście: `entity_merges` (decyzje) i kolejka przeglądu. Brak stanu poza bazą.

Konsekwencja: implementację można podmienić na natywną i porównać wyniki
**na tych samych danych wejściowych** — czyli udowodnić równoważność, a nie
zakładać ją.

### G3. Traversal grafu ma jeden interfejs

Cała logika grafowa jest w `repositories/graph.py`, za metodą `neighborhood()`.
Warstwa API nie wie, czy pod spodem jest SQL, gRPC do usługi w Ruście, czy
Apache AGE.

### G4. Kontrakty są jawne i wersjonowane

* HTTP: OpenAPI generowane z FastAPI (`/openapi.json`).
* Usługi wewnętrzne: protobuf — jeden plik `.proto` jako źródło prawdy.
* Dane: schemat bazy plus migracje Alembica są kontraktem między komponentami
  niezależnie od ich języka.

## Kandydaci do przepisania

| komponent | profil obciążenia | język | oczekiwany zysk | próg wyzwalający |
|---|---|---|---|---|
| Entity resolution — blocking i scoring par | CPU-bound, równoległy, ~10⁸ porównań stringów | **Rust** | 10–50× | pełny przebieg ER > 2 h |
| Crawler / ingestion | I/O-bound, 700 tys. żądań, wznawialny, długo działający | **Go** | pamięć 2–5×, jeden statyczny plik | import nie mieści się w oknie nocnym |
| Usługa grafowa — ścieżki, centralność, komponenty | graf w RAM (~4–8 GB), CPU-bound | **Rust** (petgraph) | ms zamiast sekund | shortest-path wchodzi do produktu |
| API | I/O-bound na Postgresie | **zostaje Python** | ~0 | nigdy |
| ETL — parsowanie i normalizacja | mieszane, dominuje I/O bazy | **zostaje Python** | mały | tylko jeśli profil wskaże |
| Frontend | — | **zostaje TypeScript** | — | — |

### Entity resolution → Rust

**Dlaczego to najlepszy kandydat.** ER to zagnieżdżona pętla po parach
z porównywaniem stringów i liczeniem cech — dokładnie ten profil, w którym Python
wypada najgorzej: narzut obiektów, brak wektoryzacji, GIL blokujący
zrównoleglenie w obrębie procesu. Przy 5 mln osób i blokowaniu dającym ~10⁸ par
do oceny różnica między Pythonem a Rustem to godziny kontra minuty.

**Ścieżka schodkowa** — każdy schodek ma własny próg i własny benchmark:

| schodek | co robimy | kiedy |
|---|---|---|
| 0 | czysty Python (stan obecny) | do ~500 tys. osób |
| 1 | `rapidfuzz` + `polars` (biblioteki natywne, kod zostaje w Pythonie) | przebieg > 30 min |
| 2 | moduł Rust przez **PyO3** — scoring w Ruście, orkiestracja w Pythonie | przebieg > 2 h |
| 3 | samodzielny job w Ruście czytający i piszący do Postgresa | przebieg > 6 h lub potrzeba ER w czasie zbliżonym do rzeczywistego |

Schodek 2 jest wart osobnego komentarza: PyO3 pozwala przepisać **tylko gorącą
pętlę**, zostawiając blokowanie, I/O i reguły biznesowe w Pythonie. To zwykle
90% zysku za 10% kosztu przepisania całego komponentu.

**Warunek równoważności:** nowa implementacja musi dać **identyczne decyzje** na
zamrożonym zbiorze 10 tys. par referencyjnych. Różnica w wyniku to błąd, nie
„inna heurystyka”.

### Crawler → Go

**Dlaczego Go, a nie Rust.** Crawler jest I/O-bound — czeka na sieć, nie liczy.
Rust nie daje tu przewagi wydajnościowej nad Go, a kosztuje znacznie więcej
w pisaniu i utrzymaniu. Go wygrywa na czymś innym:

* jeden statyczny plik wykonywalny — obraz kontenera ~15 MB zamiast ~200 MB,
* współbieżność 700 tys. zadań bez ceremonii wokół pętli zdarzeń,
* przewidywalne zużycie pamięci w procesie działającym tygodniami,
* jest w stacku zespołu, więc koszt wejścia jest bliski zeru.

**Co Go faktycznie zyskuje względem `asyncio`:** nie tyle przepustowość
(przy 1 req/s do KRS ogranicza nas rate limit, nie język), co **stabilność
procesu długo działającego** i prostotę wdrożenia. To jest argument operacyjny,
nie wydajnościowy — i tak trzeba go zapisać w ADR, żeby nikt nie uzasadniał go
później fałszywie.

**Zakres:** czytanie `ingestion_tasks`, pobieranie z rate limitem i backoffem,
zapis do `raw_documents` z deduplikacją po sha256, oznaczenie zadania.
Parsowanie **zostaje w Pythonie** — mapper jest logiką domenową, zmienia się
często i ma testy.

### Usługa grafowa → Rust

Wchodzi w grę dopiero razem z funkcją, której dziś nie ma: **najkrótsza ścieżka
między dwoma dowolnymi podmiotami** i analizy globalne (centralność, wykrywanie
społeczności). Postgres tego nie zrobi w czasie interaktywnym, a graf 1 mln
węzłów i 50 mln krawędzi mieści się w 4–8 GB RAM jako lista sąsiedztwa.

Usługa trzyma graf w pamięci, odbudowuje go z Postgresa przy starcie i po każdym
imporcie, odpowiada przez gRPC. **Nie jest źródłem prawdy** — jest indeksem,
który wolno w każdej chwili wyrzucić i zbudować od nowa.

### Czego nie przepisujemy

* **API.** Jest I/O-bound na Postgresie — czas odpowiedzi to czas zapytania SQL
  plus serializacja. Przepisanie FastAPI na Go to podręcznikowy przykład
  optymalizowania czegoś, co nie jest wąskim gardłem.
* **Parsowanie i normalizacja.** Logika domenowa o wysokiej zmienności. Python
  daje tu najkrótszą pętlę zwrotną, a koszt wykonania jest pomijalny wobec I/O.
* **Migracje i narzędzia operacyjne.** Nie ma czego optymalizować.

## Koszt, który trzeba przyjąć świadomie

System wielojęzykowy nie jest darmowy. Płacimy:

| koszt | jak go ograniczamy |
|---|---|
| trzy zestawy narzędzi w CI | osobne joby, wspólne testy kontraktowe |
| trudniejszy onboarding | granice modułów są też granicami języków — nie trzeba znać wszystkiego |
| duplikacja logiki (np. normalizacja nazw) | zbiór testów kontraktowych wspólny dla obu implementacji, uruchamiany w CI |
| debugowanie przez granicę procesów | korelacja po `ingestion_run_id` w logach wszystkich komponentów |

Ostatni punkt jest najważniejszy i najczęściej pomijany: **jeżeli normalizacja
nazw jest zaimplementowana w dwóch językach, musi istnieć wspólny zbiór
przypadków testowych** (plik JSON: wejście → oczekiwane wyjście), uruchamiany
w CI przeciwko obu implementacjom. Bez tego rozjazd jest kwestią czasu, a objawi
się cichym rozpadem grafu.

## Kolejność wprowadzania

1. **Teraz:** granice G1–G4, tabela `ingestion_tasks`, wspólny zbiór testów
   kontraktowych dla normalizacji.
2. **Gdy import przestanie mieścić się w oknie nocnym:** crawler w Go.
3. **Gdy przebieg ER przekroczy 2 h:** schodek 1 (`rapidfuzz`), potem PyO3.
4. **Gdy shortest-path wejdzie do produktu:** usługa grafowa w Ruście.

Żaden z tych kroków nie jest zaplanowany na konkretną datę. Wszystkie są
zaplanowane na konkretną **liczbę** — i to jest cała różnica.
