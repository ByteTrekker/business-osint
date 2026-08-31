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
- [x] **Zwijanie węzła osoby dla JDG** — 3 552 803 właścicieli ma dokładnie
      jedną firmę, więc węzeł osoby powtarzał tylko jej nazwę. Zwijane po
      stronie serwera, liczba w `meta`.
- [x] **„Inne firmy tej osoby" — skreślone, nie odłożone.** Osoba fizyczna może
      mieć w CEIDG jeden wpis; 18 właścicieli na 3,55 mln ma dwie firmy. To nie
      brak danych, tylko prawo. Wróci, gdy będą spółki cywilne albo CRBR.
- [x] **PRG — punkty adresowe wczytane.** 8 615 528 punktów, **1 946 032 adresy
      ze współrzędnymi (82%)**, 1 946 195 z TERYT. Mapa zbiorcza ma z czego powstać.
- [x] **Dziennik zmian podmiotu** — wyzwalacze bazy na polach nadpisywanych
      w miejscu, kanał zmian scalający je z bitemporalnością relacji przy
      odczycie. Fundament pod monitoring i alerty.
- [x] **Baza testowa na migracjach** — `create_all` nie tworzy wyzwalaczy ani
      widoków, więc schemat testowy różnił się od produkcyjnego.
- [x] **Scalanie zduplikowanych adresów** — 12 665 encji scalonych, krawędzie
      przeniesione z zachowaniem N1 i N2, każde scalenie zapisane
      w `entity_merges`. 258 grup pominiętych, bo to miejscowości o tej samej
      nazwie w różnych województwach.
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
- [ ] **Wyszukiwarka — reszta trzeciej tury.**
      - **filtr województwa** — `addresses.voivodeship` istnieje, ale prowadzi
        do niego krawędź `registered_at`, więc złączenie jest za drogie na
        ścieżce gorącej. Do rozwiązania denormalizacją albo osobnym indeksem.
      - **podpowiedzi w trakcie pisania** — etap prefiksowy kosztuje 0,3 ms,
        więc stać nas na to bez dodatkowej infrastruktury.
      - **„czy chodziło o…"** przy zerowym wyniku — trigram już liczy
        podobieństwo, tylko go nie pokazujemy.

- [x] **Mapa zbiorcza podmiotów** z grupowaniem znaczników. `/mapa`.
      Klastrowanie po stronie bazy, a nie w przeglądarce. Siatka jest
      **przeliczona raz** (`address_cells`, 297 246 komórek po 0,005 stopnia,
      migracja 0011), a zgrubniejsze poziomy zwijają się z niej w locie —
      liczenie w locie kosztowało 1,8 s na jedno przesunięcie widoku, teraz
      154 ms dla całego kraju i 18 ms dla Warszawy.
      Przeliczenie: `refresh-map`, wołane automatycznie po `import-prg`.
      - [ ] przeliczać siatkę także po `import-ceidg` i `merge-addresses` —
        dziś po tych importach mapa po cichu pokazuje poprzedni stan.
        `/map/coverage` zwraca datę przeliczenia, więc rozjazd jest widoczny,
        ale nikt na niego nie patrzy.
      - [ ] klik w skupisko → lista podmiotów pod tym adresem
        (`co-located` już to potrafi, brakuje tylko wejścia z mapy)
      - [ ] filtr po statusie i formie prawnej — mapa pokazuje dziś wszystko
        naraz, a „gdzie są spółki z o.o." to inne pytanie niż „gdzie ktokolwiek
        jest zarejestrowany"

- [ ] **UUG — rządowy geokoder GUGiK** dla 475 707 adresów, których PRG nie
      pokrył (droga uzupełniająca).
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

- [ ] **Spółki cywilne z CEIDG.** Raport „brak województwa" oznacza 3 328
      wpisów jako „działalność prowadzona wyłącznie w formie spółki cywilnej".
      To jedyna droga do prawdziwej warstwy powiązań między osobami w CEIDG —
      dziś tego pola nie czytamy wcale.
- [x] **Napisać przy mapie, że 714 771 firm nie ma adresu.** To co piąty
      przedsiębiorca; nie da się ich pokazać i mapa bez tej adnotacji wygląda
      na kompletną. Pod mapą jest teraz pełne rozliczenie: 1 946 032 z 2 421 739
      adresów widocznych (80%), 475 707 niedopasowanych do punktu PRG, plus te
      714 771 przedsiębiorców bez adresu w ogóle.
- [ ] **SUDOP** — pomoc publiczna i de minimis, na żądanie po NIP-ie.
      Aplikacja JSF bez API, ale ma eksport CSV.
- [ ] **KRZ** — upadłości, restrukturyzacje, zakazy działalności, bezskuteczne
      egzekucje. Portal publiczny bez logowania; API do znalezienia.
- [ ] **CEIDG `/firma/{id}`** — upadłości, zakazy, spółki cywilne, zarząd
      sukcesyjny. Pola są w API, nie ma ich w raportach zbiorczych.
- [ ] Suwak `as_of` w interfejsie — API to obsługuje, UI nie wystawia
- [ ] **REGON / GUS** — wniosek o bezpłatny klucz. Największy możliwy przyrost:
      z 3,6 mln do ~5 mln podmiotów plus adresy i PKD.
- [ ] **KRS masowo** — art. 60a ustawy o KRS penalizuje nieuprawnione
      pozyskiwanie danych przez usługi sieciowe, a zakres pojęcia jest niejasny.
      Potrzebna opinia prawnika przed jakimkolwiek przemiataniem rejestru.

## Dług techniczny

- [ ] Kolejka przeglądu dla entity resolution — klucz blokujący jest zapisywany,
      ale nigdzie nie wykorzystywany. Miał generować kandydatów do ręcznej
      oceny; dziś jest martwym polem.
- [ ] Testy jednostkowe dla nowych źródeł (CEIDG, CIT, BZP, geokoder)
- [ ] Ścieżka dockerowa nadal nieuruchomiona ani razu. `make test-integration`
      już jej nie używa; zostają `make up`, `make psql` i `make bench`.
