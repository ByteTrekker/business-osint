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
- [x] **Asercje jakości danych** — `check-data`, siedem kontroli, każda
      wywiedziona z realnej awarii. Pierwsze uruchomienie wykryło złamanie N2
      na 98,9% grafu.
- [x] **Fixture KRS zastąpiony prawdziwym odpisem** — poprzedni opisywał
      schemat wymyślony, z niezamaskowanymi nazwiskami i `naglowekA` w złym
      miejscu. Testy przechodziły, opisując API, które nie istnieje.

## Do zrobienia — pilne

- [ ] **Bramki jakości i commit.** Od importu CEIDG nazbierało się bardzo dużo
      niezacommitowanego kodu. To największe bieżące ryzyko w projekcie.
- [ ] **Naprawić pochodzenie krawędzi (N2).** Kontrole jakości pokazały, że
      **6 392 682 z 6 466 459 krawędzi nie ma wpisu w `relationship_sources`** —
      98,9% grafu. Cały defekt jest w imporcie masowym CEIDG, który pisze relacje
      zbiorczym SQL-em i nigdy nie dotyka tabeli pochodzenia — GLEIF i BZP
      zapisują je komplet. W bazie leży 341 dokumentów źródłowych i 77 004 wpisy
      pochodzenia. Bez tego nie da się ani zweryfikować twierdzenia, ani obronić
      go przed osobą, której dotyczy. Do zrobienia razem z reimportem CEIDG.

- [ ] **Reimport CEIDG** — poprawiony format adresu (`ul. Kąty 14, 34-443
      Sromowce Wyżne` zamiast członów rozdzielonych przecinkami) oraz zapis
      numeru budynku i lokalu do osobnych kolumn. Około 40 minut.

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
- [ ] „1 powiązań" — liczebnik nieodmieniony w liście wyników i na profilu.

## Do zrobienia — funkcje

- [ ] **KRS jako wzbogacanie na żądanie** + mechanizm TTL. Mapper gotowy
      i przetestowany: daje 25 lat datowanej historii — nazwy, siedziby, kapitał,
      każda zmiana z numerem i datą wpisu. To jedyne źródło prawdziwej historii.
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
- [ ] „Kto jeszcze pod tym adresem" i „inne firmy tej osoby" — mamy komplet
      danych, tylko tego nie liczymy
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
- [ ] Ścieżka dockerowa nadal nieuruchomiona ani razu
