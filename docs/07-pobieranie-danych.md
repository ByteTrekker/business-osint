# Pobieranie danych: odporność, koszt, przyrostowość

Dokument odpowiada na cztery pytania: co jest najtańsze do pobrania, co da się
pobierać przyrostowo, ile realnie daje asynchroniczność i kiedy Python przestaje
wystarczać.

Wszystkie liczby pochodzą z `etl/fetching/profiles.py` — są **szacunkami do
zweryfikowania przy pierwszym imporcie**, ale są zapisane w kodzie, więc plan
i implementacja nie mogą się rozjechać.

## 1. Warstwa odporności

Cztery mechanizmy, wszystkie w `etl/fetching/`, wszystkie objęte testami bez
sieci i bez realnego czekania (zegar i `sleep` są wstrzykiwane):

| mechanizm | plik | co rozwiązuje |
|---|---|---|
| **ponawianie z wykładniczym backoffem** | `policy.py` | chwilowe 5xx i timeouty |
| **rozrzut losowy (jitter)** | `policy.py` | fala zapytań, gdy serwis wraca do życia |
| **`Retry-After`** | `client.py` | serwer sam mówi, kiedy wrócić |
| **limit tempa (token bucket)** | `rate_limit.py` | nie dostajemy bana za dobijanie |
| **bezpiecznik** | `circuit.py` | martwy rejestr nie zjada budżetu prób |
| **kolejka w Postgresie** | `task_queue.py` | przerwany przebieg wznawia się, nie zaczyna od zera |

Kontrakt, który to spina:

> **Warstwa pobierania nie wypuszcza wyjątków `httpx` ani `asyncio` — wyłącznie
> `FetchError`. Pojedyncze nieudane zadanie nigdy nie przerywa przebiegu.**

Podział błędów jest tu istotą, nie formalnością:

* **404** — poprawna odpowiedź rejestru. Nie ponawiamy, nie otwieramy bezpiecznika.
* **4xx** — nasz błąd (zły parametr, brak tokenu). Nie ponawiamy i **nie**
  obciążamy bezpiecznika, bo rejestr działa poprawnie.
* **429, 5xx, timeout, zerwane połączenie** — ponawiamy i liczymy do bezpiecznika.
* **niepoprawny JSON** — traktujemy jako trwały: ponowienie nie naprawi parsera.

### Wznawialność

Kolejka `ingestion_tasks` (migracja `0002`) pobiera partie przez
`FOR UPDATE SKIP LOCKED`, więc wielu workerów bierze rozłączne zbiory bez
brokera. Zadanie kończy się jako `done`, `skipped`, albo wraca do puli
z opóźnieniem i licznikiem prób; po `MAX_TASK_ATTEMPTS` zostaje jako `failed`
razem z treścią błędu — **nie znika po cichu**. `release_stale_locks()` odzyskuje
zadania po workerze, który padł w trakcie.

Kolejka leży w Postgresie, a nie w Redisie, z dwóch powodów: nie dokłada
infrastruktury na MVP i mieści się w tej samej transakcji, co zapis wyniku, więc
zadanie nie może zniknąć między pobraniem a zapisem.

## 2. Co jest najtańsze do pobrania

Posortowane po czasie pełnego przebiegu (`sorted_by_cost()`):

| źródło | dostęp | obiekty | rozmiar | pełny przebieg |
|---|---|---:|---:|---:|
| Dotacje UE | plik zbiorczy | 300 tys. | 150 MB | minuty |
| Biała lista VAT | plik zbiorczy | 3 mln | 2,5 GB | ~2 min pobierania |
| REGON / GUS | plik zbiorczy | 5 mln | 3 GB | ~2 min pobierania |
| TED | paczki dzienne | 1 mln | 8 GB | ~7 min pobierania |
| BZP | API po dacie | 250 tys. | 400 MB | ~1,7 h |
| CEIDG | API po dacie | 2,5 mln | 2 GB | ~1,2 dnia |
| CRBR | zapytanie na podmiot | 600 tys. | 6 GB | ~6,9 dnia |
| **KRS** | zapytanie na podmiot | 700 tys. | 120 GB | **~8,1 dnia** |

Wniosek, który zmienia kolejność prac: **wszystko, co jest plikiem zbiorczym,
pobiera się w minutach.** Czas przebiegu jest zdominowany przez parsowanie
i zapis do bazy, nie przez sieć. Dwa źródła zapytań-na-podmiot (KRS i CRBR)
kosztują razem 15 dni i to one wyznaczają harmonogram.

Do tego dochodzi GLEIF (relacje właścicielskie, dzienny plik zbiorczy) — nie ma
go jeszcze w profilach, ale należy do tej samej, taniej kategorii.

## 3. Co da się pobierać przyrostowo

| tryb | źródła | jak działa |
|---|---|---|
| **plik zmian** | REGON, Biała lista, TED | dostawca publikuje deltę — pobieramy tylko ją |
| **zakres dat** | BZP, CEIDG | filtrujemy po dacie publikacji lub modyfikacji |
| **hash treści** | **KRS, CRBR** | brak wsparcia po stronie rejestru |
| **tylko pełne** | Dotacje UE | zbiór jest tak mały, że delta się nie opłaca |

**KRS nie ma kanału zmian i to jest główny problem operacyjny projektu.**
Trzy sposoby radzenia sobie z tym, w kolejności wdrażania:

1. **Dedup po `content_sha256`.** Ponowne pobranie niezmienionego odpisu nie
   tworzy nowego snapshotu ani nie uruchamia parsowania. Oszczędza bazę i CPU,
   ale nie oszczędza zapytań — nadal trzeba odpytać każdy podmiot.
2. **Priorytety zamiast równomiernego przemiatania.** Spółka z ruchem
   w rejestrze, w przetargach albo z powiązaniami w obserwowanych podmiotach
   dostaje wyższy `priority` w kolejce. 80% wartości pochodzi z kilku procent
   podmiotów; przemiatanie wszystkich z jednakową częstotliwością jest
   marnotrawstwem.
3. **MSiG jako kanał zmian dla KRS.** Monitor Sądowy i Gospodarczy publikuje
   ogłoszenia o wpisach. Jeśli uda się z niego wyciągnąć numery KRS, zamienia
   ślepe przemiatanie w celowane odświeżanie: pobieramy tylko te podmioty,
   o których wiadomo, że się zmieniły. To jest największa pojedyncza
   optymalizacja dostępna w tym projekcie — z 8 dni robi kilka minut dziennie.

## 4. Ile naprawdę daje asynchroniczność

Odpowiedź jest niewygodna: **dla najdroższych źródeł prawie nic.**

| źródło | c=1 | c=10 | dlaczego |
|---|---|---|---|
| KRS | 8,1 dnia | **8,1 dnia** | ogranicza nas limit tempa 1 req/s, nie latencja |
| CRBR | 6,9 dnia | **6,9 dnia** | jak wyżej |
| BZP (5 req/s, c=8) | ~4 h | ~1,7 h | limit pozwala na równoległość |
| pliki zbiorcze | minuty | minuty | jeden strumień, nie ma czego zrównoleglać |

Dla porównania — gdyby jedynym ograniczeniem była latencja 300 ms, KRS
zająłby 2,4 dnia przy c=1 i 0,24 dnia przy c=10. Ale nie jest, bo sami
narzucamy sobie 1 req/s z uprzejmości wobec rejestru bez SLA.

**Wniosek:** asynchroniczność jest tu potrzebna do czegoś innego niż
przyspieszenie. Daje:

* **równoległość między źródłami** — KRS, CRBR i BZP jadą jednocześnie, każde
  z własnym limiterem, w jednym procesie zamiast trzech;
* **odporność** — jedno zawieszone połączenie nie blokuje pozostałych;
* **niskie zużycie zasobów** — 700 tys. zadań w pętli zdarzeń zamiast puli wątków.

Przyspieszenie przyjdzie z pobierania przyrostowego i priorytetów, **nie
z równoległości**. To jest pierwsza rzecz, którą trzeba sobie powiedzieć, zanim
zacznie się optymalizować crawler.

## 5. Kiedy Python przestanie wystarczać

Zgodnie z ADR-0005 rozstrzyga zmierzony próg, nie przeczucie.

**Pobieranie jest ograniczone I/O i limitem tempa — Python jest tu w porządku
i pozostanie.** Przy 1 req/s narzut interpretera jest niemierzalny. Go dałoby
mniejsze zużycie pamięci i jeden plik wykonywalny, ale nie większą przepustowość.

**Parsowanie to inna historia** i tam Python może przegrać:

| zadanie | rozmiar | ryzyko |
|---|---|---|
| odpisy KRS (JSON) | 120 GB przy pełnym przebiegu | wysokie |
| Biała lista (płaski plik) | 2,5 GB dziennie | średnie |
| TED (XML) | 8 GB | średnie |
| REGON (CSV) | 3 GB | niskie — to zadanie dla Polarsa |

Kolejność działań, gdy parsowanie stanie się wąskim gardłem:

1. **`orjson` zamiast `json`** — zwykle 2–5× na dużych dokumentach, jedna linia zmiany.
2. **`lxml` z `iterparse`** dla TED — parsowanie strumieniowe zamiast wczytywania
   całego drzewa.
3. **Polars** dla CSV z REGON i Białej listy.
4. **`COPY` zamiast `INSERT`** przy ładowaniu — bardzo często to baza jest wąskim
   gardłem, a nie parser. Sprawdzić **zanim** zmieni się język.
5. Dopiero potem **Rust**, i tylko dla konkretnego parsera.

**Próg wyzwalający:** parsowanie zajmuje więcej niż 30% czasu przebiegu **oraz**
przebieg nie mieści się w oknie nocnym. Oba warunki naraz — samo „parser jest
wolny” nie wystarczy, jeśli i tak czekamy na rejestr.

Uwaga, która sprowadza dyskusję na ziemię: przy KRS pobranie trwa 8 dni,
a parsowanie 700 tys. dokumentów w Pythonie to kwestia godzin. **Nawet parser
dziesięciokrotnie wolniejszy niż optymalny nie jest tu wąskim gardłem.**
Przepisywanie go byłoby optymalizacją 2% czasu przebiegu.

## 6. Kolejność wdrażania

1. **Pliki zbiorcze najpierw** — REGON, Dotacje UE, GLEIF. Minuty pracy,
   natychmiastowe pokrycie bazy podmiotami i pierwsze krawędzie właścicielskie.
2. **KRS w tle, z priorytetami**, od jednego województwa. Ośmiodniowy przebieg
   startuje raz i pracuje sobie z boku.
3. **BZP i CEIDG** — przyrostowe po dacie, więc tanie w utrzymaniu.
4. **CRBR** — drogie, ale to jedyne źródło beneficjentów rzeczywistych.
5. **MSiG** — gdy tylko okaże się wykonalne, bo zamienia KRS z przemiatania
   w nasłuchiwanie.
