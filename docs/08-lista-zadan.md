# Lista zadań

Stan na koniec sesji importowej. Kolejność w każdej sekcji odpowiada
priorytetowi, nie chronologii.

## Zrobione

- [x] **Wyszukiwarka etapowa** — z HTTP 500 po 5 s do 7–77 ms. Identyfikator →
      prefiks (btree, 0,3 ms) → nazwisko → trigram na żądanie. Trigram przy
      9,5 mln encji kosztuje sekundy, więc nie może być ścieżką domyślną.
- [x] **Osobny silnik bazy dla ETL** — `statement_timeout` 5 s właściwy dla API
      zabił zadania wsadowe pięć razy z rzędu.
- [x] **Naprawa fałszywych scaleń** — dwa niezależne defekty tej samej klasy:
      SQL CEIDG łączył encje po znormalizowanej nazwie, a `EntityResolver`
      po dwunastoznakowym kluczu blokującym (dzieli go 49 704 firm zaczynających
      się od „PRZEDSIĘBIORSTWO"). Oba naprawione: **tożsamość wyłącznie po
      twardym identyfikatorze**.
- [x] Profil podmiotu: status, oś życia, finanse, kontakt
- [x] **PKD rozwijane z opisami** — na poziomie działu, bo klas nie ma
      w otwartych danych
- [x] **Mapa adresu** — geokodowanie Nominatim raz na adres, wynik w bazie
- [x] **Ranking wyszukiwarki** — trzy etapy prefiksowe (dokładny → do granicy
      słowa → dowolny) plus trafność łącząca pokrycie nazwy, obecność KRS,
      status i stopień. „ORLEN" zwraca ORLEN S.A., nie „Orlena Hintzke".
- [x] **Usunięty indeks GiST** — 2,1 GB, największy w bazie, użyty 26 razy
      i psujący plany (`normalized_name = 'orlen'` szło z 0,2 ms na 555 ms).
- [x] **„Kto jeszcze pod tym adresem"** — z paginacją i ostrzeżeniem przy
      adresach zbiorczych. Przyjmuje id podmiotu albo id adresu.
- [x] **Stan rejestracji LEI** — wyciągnięty z już pobranych dokumentów, bez
      sieci. 15 424 spółek ma LEI oznaczony `LAPSED`; ta informacja leżała
      nieużywana. Historia nazwy z wygasłego rekordu dotyczy **14 spółek**,
      nie wszystkich z GLEIF — wcześniejsze oszacowanie było zawyżone.
- [x] **Odmiana liczebnika** — „1 powiązanie”, nie „1 powiązań”.
- [x] **„Nie znaleziono nazwy…”** przy wyniku z dopasowania rozmytego.
- [x] **Szukanie po adresie** — rozdzielone dwie role adresu: klucz scalania
      zostaje sklejony, pole wyszukiwania dostaje granice słów. 2,4 mln wierszy
      przepisanych partiami. „chemikow plock" → 6 ms zamiast zera wyników.
- [x] **Wyszukiwarka — druga tura**: kolejność słów przez indeks pełnotekstowy
      (0,148 ms zamiast 200 ms trigramem) i filtr stanu działalności.
- [x] **Paginacja** — wyszukiwarka i powiązania, z `meta` w kontrakcie.
      Ujawniła pluskwę: etap szerokiego prefiksu gubił wyniki na dalszych
      stronach, bo duplikaty zjadały jego limit.
- [x] **KRS jako wzbogacanie na żądanie** — `enrich-krs`, endpoint
      `POST /entities/{id}/enrich/krs`, czas życia odpisu 30 dni, historia nazw
      i kapitału w interfejsie. Historia była wcześniej liczona i wyrzucana.
- [x] **Kontrole danych wpięte w bramki i w ETL** — `make data-check`,
      `make check-db`, plus werdykt po każdym imporcie. Przy okazji naprawiony
      `make test-integration`, który szedł przez Dockera i nie wykonał się nigdy.
- [x] **Bramki, commity i push** — 10 commitów w PR #2, stos PR #2 → #3 → #4.
- [x] **Reimport CEIDG z naprawą pochodzenia** — krawędzie bez źródła
      6 392 682 → 733, adresy z numerem budynku 0 → 2 373 660, zero skasowanych
      wierszy. Pozostałe 733 to dług z importu sprzed wprowadzenia pochodzenia,
      którego raport źródłowy już nie istnieje; kontrola ma na to opisany próg.
- [x] **Zbadane 22 encje z dwoma LEI-ami** — scalanie było poprawne, kontrola
      za szeroka. GLEIF wystawia rekordy `DUPLICATE` i `LAPSED`, więc jedna
      spółka legalnie nosi dwa LEI-e przy jednym KRS-ie.
- [x] **Asercje jakości danych** — `check-data`, siedem kontroli, każda
      wywiedziona z realnej awarii. Pierwsze uruchomienie wykryło złamanie N2
      na 98,9% grafu.
- [x] **Fixture KRS zastąpiony prawdziwym odpisem** — poprzedni opisywał
      schemat wymyślony, z niezamaskowanymi nazwiskami i `naglowekA` w złym
      miejscu. Testy przechodziły, opisując API, które nie istnieje.

## Do zrobienia — pilne


## Znalezione przy okazji

- [ ] **ORLEN S.A. jest w bazie dwa razy** — raz z KRS 0000028860 (z GLEIF),
      raz z NIP 7740001454 (z CIT). Encje nie mają wspólnego identyfikatora,
      więc entity resolution nie ma prawa ich scalić i słusznie tego nie robi.
      Rozwiązaniem jest wzbogacenie z KRS: odpis zawiera **oba** numery naraz,
      co daje legalną podstawę scalenia w rozumieniu niezmiennika N4.

      Skala: 23 683 podmioty mają KRS bez NIP-u, 3 560 214 mają NIP bez KRS-u.
      Zbieżnych nazw jest **447** — i to jest górne oszacowanie liczby duplikatów
      możliwych do wykrycia dziś, a nie lista do scalenia. Zbieżność nazw
      niczego nie dowodzi (N4), więc scalenie i tak wymaga odpisu KRS jako
      źródła wspólnego identyfikatora. Prawdziwa liczba duplikatów jest większa,
      bo obejmuje też pary o różnym zapisie nazwy.
- [ ] **Adres tej samej siedziby jako dwie encje** — ORLEN ma
      `Chemików 7, 09-411 Płock` z odpisu KRS i `Płock Chemików 7, 09-411, Płock`
      z wcześniejszego importu. Normalizacja adresu różni się między źródłami
      i trzeba ją ujednolicić, zanim dojdzie dopasowanie do punktów PRG.
- [ ] **Wyszukiwarka — reszta trzeciej tury.**
      - **filtr województwa** — `addresses.voivodeship` istnieje, ale prowadzi
        do niego krawędź `registered_at`, więc złączenie jest za drogie na
        ścieżce gorącej. Do rozwiązania denormalizacją albo osobnym indeksem.
      - **podpowiedzi w trakcie pisania** — etap prefiksowy kosztuje 0,3 ms,
        więc stać nas na to bez dodatkowej infrastruktury.
      - **„czy chodziło o…"** przy zerowym wyniku — trigram już liczy
        podobieństwo, tylko go nie pokazujemy.

- [ ] **Mapa zbiorcza podmiotów** z grupowaniem znaczników.
      - klastrowanie po stronie serwera: agregacja po siatce zależnej od poziomu
        przybliżenia, zwracamy liczności zamiast punktów — 2,4 mln znaczników
        nie ma prawa trafić do przeglądarki
      - rozdzielanie klastrów przy przybliżaniu
      - **warunek wstępny: współrzędne dla całej bazy.** Nominatim przy limicie
        1 zapytania na sekundę to 28 dni odpytywania cudzej infrastruktury —
        to nie jest droga. Zbadane 2026-08-31, są dwie realne:

- [ ] **PRG — masowy import punktów adresowych** (droga główna).
      `https://opendata.geoportal.gov.pl/prg/adresy/PRG-punkty_adresowe.zip`
      — 1,79 GB, SHP, bez uwierzytelniania i bez ograniczeń, ~7 mln punktów
      adresowych dla całego kraju. Bezpłatne i do dowolnego wykorzystania,
      także komercyjnego (rozporządzenie RM z 16.07.2021, Dz.U. 2021 poz. 1373).
      Miejsca starczy: 294 GB wolnego, baza zajmuje 12 GB.
      Uwaga: serwer **ignoruje nagłówek `Range`**, więc pobranie jest
      jednorazowe i całościowe — wznawianie odpada, trzeba to uwzględnić
      w zadaniu ETL.
      Współrzędne są w EPSG:2180 (PUWG 1992), do mapy trzeba je przerzutować
      na WGS84 — `pyproj` robi to poprawnie, sprawdzone na znanym punkcie.

- [ ] **UUG — rządowy geokoder GUGiK** (droga uzupełniająca, dla adresów,
      których PRG nie pokryje).
      `https://services.gugik.gov.pl/uug/?request=GetAddress&address=...`
      Format zapytania to **`Miasto, Ulica Numer`** — przecinek po mieście jest
      obowiązkowy, bez niego usługa nie trafia. Zmierzone na 40 prawdziwych
      adresach z naszej bazy: **35 trafień, 5 pudeł, 0 błędów**, 430 ms na
      zapytanie sekwencyjnie (z czego 4 ms po stronie serwera — reszta to sieć),
      2,3 zapytania na sekundę.
      Zwraca więcej niż współrzędne: **TERYT, SIMC, ULIC** i kod pocztowy.
      To jest osobna wartość — daje twarde identyfikatory administracyjne
      do łączenia adresów, których dziś nie mamy.
      Dokładniejszy od Nominatima: dla adresu testowego różnica 75 m, bo PRG
      wskazuje punkt adresowy budynku, a Nominatim interpoluje wzdłuż ulicy.

- [ ] **SUDOP** — pomoc publiczna i de minimis, na żądanie po NIP-ie.
      Aplikacja JSF bez API, ale ma eksport CSV.
- [ ] **KRZ** — upadłości, restrukturyzacje, zakazy działalności, bezskuteczne
      egzekucje. Portal publiczny bez logowania; API do znalezienia.
- [ ] **CEIDG `/firma/{id}`** — upadłości, zakazy, spółki cywilne, zarząd
      sukcesyjny. Pola są w API, nie ma ich w raportach zbiorczych.
- [ ] Suwak `as_of` w interfejsie — API to obsługuje, UI nie wystawia
- [ ] „Inne firmy tej osoby" — dla właścicieli JDG i wspólników. Analogiczne
      do sąsiadów spod adresu, tylko po krawędzi `sole_proprietor_of`.
- [ ] Zwijanie węzła osoby w węzeł firmy dla JDG — dziś graf pokazuje
      „Jacek Gadomski → właściciel → Jacek Gadomski", co jest szumem

## Zablokowane na zewnątrz

- [ ] **REGON / GUS** — wniosek o bezpłatny klucz. Największy możliwy przyrost:
      z 3,6 mln do ~5 mln podmiotów plus adresy i PKD.
- [ ] **KRS masowo** — art. 60a ustawy o KRS penalizuje nieuprawnione
      pozyskiwanie danych przez usługi sieciowe, a zakres pojęcia jest niejasny.
      Potrzebna opinia prawnika przed jakimkolwiek przemiataniem rejestru.

## Dług techniczny

- [ ] Kolejka przeglądu dla entity resolution — klucz blokujący jest zapisywany,
      ale nigdzie nie wykorzystywany. Miał generować kandydatów do ręcznej
      oceny; dziś jest martwym polem.
- [ ] `entity_changes` — tabela zdarzeń domenowych pod alerty. Dopisanie
      wstecz oznacza utratę historii.
- [ ] Testy jednostkowe dla nowych źródeł (CEIDG, CIT, BZP, geokoder)
- [ ] Ścieżka dockerowa nadal nieuruchomiona ani razu. `make test-integration`
      już jej nie używa; zostają `make up`, `make psql` i `make bench`.
