# Dziennik działań

Chronologiczny zapis tego, **co zrobiono i z czego to wynikło**. Nie jest to
lista zmian — od tego jest `git log`. Tutaj trafia droga: jaki był objaw, co
pomiar pokazał, jaką decyzję podjęto i czego ta decyzja kosztowała.

Zasada: wpis powstaje wtedy, gdy coś **zaskoczyło**. Zadanie wykonane zgodnie
z planem nie potrzebuje wpisu; wystarczy commit. Wpis jest po to, żeby za pół
roku dało się odtworzyć rozumowanie, którego nie widać w kodzie.

Kolejność odwrotna — najnowsze na górze.

---

## 2026-08-31 — Wyszukiwarka, druga tura

**Kolejność słów.** „termika orlen" nie trafiało w ORLEN TERMIKA, bo żaden etap
prefiksowy tego nie zrobi — zapytanie nie jest początkiem nazwy. Ratował to
dopiero trigram, poprawnie, ale w setkach milisekund. Indeks pełnotekstowy GIN
odpowiada w **0,148 ms** i jest niezależny od kolejności.

Konfiguracja `simple`, nie `polish` — tej drugiej PostgreSQL nie ma, a i tak
byłaby niewłaściwa: nazwy firm nie są językiem naturalnym i sprowadzanie do
rdzenia zlepiałoby odrębne znaki towarowe. Indeks jest wyrażeniowy, nie na
kolumnie `tsvector`: kolumna oznaczałaby przepisanie 9,5 mln wierszy i stałe
pilnowanie spójności. Zbudował się w 26 s i waży 290 MB — mieści się z zapasem
w 2,1 GB odzyskanych po usunięciu GiST.

Semantyka jest **koniunkcyjna**. Alternatywa dla „jan kowalski" zwracałaby pół
bazy. Zapytania z wyrazami spoza nazwy — jak „PKN ORLEN", gdzie w bazie stoi
samo „orlen" — obsługuje nadal trigram na końcu, 200 ms.

**Szukanie po adresie nie działa z zupełnie innego powodu, niż zakładałem.**
Sądziłem, że to kwestia kolejności słów. Otóż nie: adresy mają
`normalized_name` sklejone w jeden ciąg — `chemikow732566alwernia` — bo
normalizacja usuwa spacje. FTS widzi tam **jeden token** i nie ma czego szukać.
To jest problem kształtu danych, nie zapytania, i wymaga rozdzielenia dwóch
ról: `addresses.normalized` jest kluczem naturalnym do scalania i musi zostać
sklejony, a `entities.normalized_name` jest polem wyszukiwania i powinien mieć
granice słów. Osobne zadanie, bo dotyka 2,4 mln wierszy.

**Filtr statusu — i pułapka, która go po cichu wyłączyła.** Podmiana w pliku
nie weszła, bo wzorzec rozjechał się o komentarz dodany wcześniej. Zapytanie
poszło **bez** klauzuli filtrującej, a parametr `:status` był dalej
przekazywany — i SQLAlchemy zignorowało go bez słowa. Objaw: wszystkie trzy
wartości statusu zwracały identyczne wyniki, łącznie z `inactive`, dla którego
w bazie nie ma ani jednego podmiotu. Nic tego nie zgłosiło: ani lint, ani mypy,
ani żaden test. Wyszło dopiero przy porównaniu wyników dla trzech wartości.

Wniosek na przyszłość: nieużywany parametr wiązany jest cichy i trzeba go
sprawdzać zachowaniem, a nie obecnością w kodzie.

**Filtr obowiązuje też w trigramie**, ale **nie** w wyszukiwaniu po
identyfikatorze. Kto podał NIP, chce tę encję — nawet wykreśloną. Filtr stanu
jest narzędziem przeglądania, nie cenzurą wyniku dokładnego.

---

## 2026-08-31 — Paginacja i pluskwa, którą wykryła

**Skąd.** API zwracało `limit` i nic poza tym. Lista powiązań ucięta na dwustu
wierszach wyglądała **identycznie** jak lista, która na dwustu się kończy —
klient nie miał żadnego sygnału, że czegoś nie widzi. To jest naruszenie
niezmiennika N3, tylko po stronie kontraktu, a nie traversalu.

**Decyzja: przesunięcie, nie kursor.** Kursor po `(score, id)` byłby
teoretycznie ładniejszy, ale wyszukiwarka jest etapowa i żeby oddać stronę n,
i tak musi pobrać wszystko, co ją poprzedza. Przesunięcie jest uczciwsze wobec
tego, jak to naprawdę działa, i prostsze. Ograniczone do 1000 — kto potrzebuje
więcej wyników, potrzebuje eksportu, a nie przewijania.

**`total` bywa `null` i to jest świadome.** Dla powiązań liczymy dokładnie,
bo to jedno tanie zapytanie. Dla wyszukiwania pełny przelicznik oznaczałby
przejście przez wszystkie dopasowania — przy prefiksie „a" to 830 tys. wierszy.
Mówimy więc tylko, czy jest coś dalej. Zmyślona liczba byłaby gorsza od
przyznania się do jej braku, a interfejs pokazuje zakres zamiast „strona 7 z 12".

**Pluskwa, którą stronicowanie ujawniło.** Przy `offset=20` wracał **jeden**
wynik zamiast trzech. Przyczyna: każdy etap pytał o `needed - len(rows)`
wierszy, a etap szerokiego prefiksu zwraca **nadzbiór** dwóch poprzednich —
jego limit zjadały duplikaty odrzucane dopiero po pobraniu. Bez stronicowania
ten błąd był niewidoczny, bo pierwsza strona zawsze wychodziła kompletna.
Każdy etap pyta teraz o pełną liczbę i polega na odsiewaniu duplikatów.

Do zapytań doszedł też `e.id` jako ostatni element porządku. Bez niego wiersze
o równej trafności wracają w kolejności zależnej od planu, a wtedy przy
stronicowaniu ten sam podmiot potrafi pojawić się dwa razy albo zniknąć.

**Test, który to złapałby wcześniej.** Nie sprawdzamy liczników, tylko czy
**sklejone strony dają dokładnie ten sam zbiór** co jedno duże zapytanie. Test
na samych licznikach przeszedłby także przy dublowaniu i gubieniu wyników.

**Znalezione przy okazji.** ORLEN ma dwie encje adresu tej samej siedziby:
`Chemików 7, 09-411 Płock` z odpisu KRS i `Płock Chemików 7, 09-411, Płock`
z wcześniejszego importu. Normalizacja adresu różni się między źródłami.

---

## 2026-08-31 — KRS na żądanie: historia była liczona i wyrzucana

**Objaw, którego nie było widać.** Mapper KRS produkował datowaną historię
nazw, siedzib i kapitału — i nic z tego nie trafiało do bazy. `EntityResolver`
wypełnia tabelę `companies` **wyłącznie przy tworzeniu encji**, a encja
z numerem KRS zwykle już istnieje, bo przyszła z GLEIF albo z CEIDG.
Dopasowanie po identyfikatorze nie aktualizowało niczego. Kod działał, testy
mappera przechodziły, a efekt był zerowy.

**Decyzja.** Osobny krok `apply_company_facts`, który przenosi fakty z odpisu na
istniejący wiersz. Atrybuty dopisujemy **scaleniem** (`||`), nie podmianą:
`companies.attributes` może już nieść dane z innego źródła, a odpis ma je
uzupełnić, nie wymieść. Przenosimy jawną listę pól, nie „wszystko, co przyszło" —
cicha zgoda na dowolne pole oznacza, że zmiana w mapperze wsypuje do bazy rzeczy,
na które nikt się nie zgodził.

**Czas życia dokumentu: 30 dni.** Wpisy w KRS zmieniają się w tempie miesięcy,
a każde pobranie obciąża rejestr ministerstwa. Świeżość liczymy po **dokumencie**,
nie po encji — ten sam odpis dotyczy spółki i jej wspólników korporacyjnych,
a pobranie ma kosztować raz.

**Pułapka asyncpg, drugi raz ta sama klasa.** `CAST(:registered_on AS date)`
sprawia, że asyncpg wnioskuje typ parametru jako `date` i **odrzuca napis**:
`invalid input for query argument $3: '2001-07-19'`. Konwersja musi być po
stronie Pythona — `dt.date` i `Decimal`, nie `str`. Ani ruff, ani mypy tego nie
widzą, bo to surowy SQL; wychodzi dopiero na żywym połączeniu.

**Wynik na ORLEN-ie.** Forma prawna z nieczytelnego kodu GLEIF `FJ0E` na
`SPÓŁKA AKCYJNA`, data rejestracji 2001-07-19, kapitał 1 451 177 561,25 zł,
dwie nazwy w historii (zmiana z „POLSKI KONCERN NAFTOWY ORLEN" 3 lipca 2023),
cztery zmiany kapitału, 68 wpisów w organie reprezentacji. Powtórne wywołanie
pomija pobranie: „odpis z 2026-08-31 jest w czasie życia".

**Drobiazg z interfejsu.** Napisałem CSS na zmiennej `--border`, która w tym
projekcie nie istnieje — nazywa się `--line`. Oś czasu renderowała się bez
linii, a nic nie zgłosiło błędu: nieistniejąca zmienna CSS to po prostu pusta
wartość. Wyszło dopiero przy sprawdzeniu wyliczonych stylów w przeglądarce.

---

## 2026-08-31 — Kontrole danych faktycznie się uruchamiają

**Objaw, którego nikt nie zgłosił.** Moduł `etl.quality` ma w docstringu
„asercje uruchamiane po imporcie". Przez dobę nie wołała go **żadna** komenda.
To jest dokładnie to samo przeoczenie, które opisuje jego własny docstring:
zapytanie wykrywające 69 tys. fałszywych scaleń też dało się napisać w minutę
i też nikt go nie napisał.

**Decyzja.** Każda komenda ETL kończy się werdyktem kontroli. Raport **nie**
przerywa procesu kodem błędu, bo kontrole mierzą stan całej bazy — import,
który zrobił swoje, nie może wyglądać na nieudany z powodu długu sprzed
tygodnia. Twardą bramką jest `make data-check` z kodem wyjścia 1.

**Pułapka, na którą prawie wszedłem.** Kontrole musiały pójść w **tej samej
pętli zdarzeń** co import. Drugie `asyncio.run()` dostałoby połączenia przypięte
do już zamkniętej pętli — ta sama pułapka kosztowała już raz debugowanie przy
imporcie GLEIF. Stąd `_with_data_check`, który opakowuje korutynę importu,
zamiast uruchamiać kontrole osobno.

**Znalezione przy okazji.** `make test-integration` szedł przez
`docker compose exec` i **nie wykonał się ani razu** — demon Dockera jest
wyłączony przez całą historię tego projektu. CI tymczasem uruchamia te testy
natywnie, przeciwko usłudze Postgresa. Cel w Makefile obiecywał coś, czego nigdy
nie zrobił, co jest gorsze niż jego brak, bo czyta się jak pokrycie. Zrównany
z tym, co robi CI i co i tak uruchamiałem ręcznie.

**Czego nie zrobiłem.** `check-data` nie trafia do CI. Baza CI jest pusta po
migracjach, więc każda kontrola przeszłaby tam zawsze. W CI biegną za to testy
samych kontroli, i to one mają wartość.

---

## 2026-08-31 — Reimport CEIDG i dwa naruszenia, które nim nie zniknęły

**Wynik reimportu.** 17 województw, 3 562 642 wiersze, zero błędów. Krawędzie
bez pochodzenia: **6 392 682 → 733**, czyli 99,99% naprawione. Adresów z numerem
budynku: 0 → 2 373 660, co zdejmuje blokadę z mapy zbiorczej. Encji przybyło
169 — naprawa poszła w miejscu, nic nie zostało skasowane.

**733 krawędzie, których reimport nie mógł naprawić.** To 372 realne, aktywne
firmy z poprawnymi NIP-ami, zaimportowane 30 sierpnia. Raporty CEIDG są
migawkami i tych wpisów w bieżących już nie ma. Mieliśmy dla nich źródło —
raport z 30 sierpnia — tylko go nie zapisaliśmy, a pliku już nie posiadamy.

Decyzja właściciela projektu: zostawić. Wymyślenie im dokumentu źródłowego
byłoby gorsze niż policzenie ich. Kontrola dostała **próg 733 z komentarzem**,
dokładny a nie zaokrąglony: 734. naruszenie to regresja. To jedyne miejsce
w tym module, gdzie próg jest różny od zera.

**Uwaga na skutek uboczny progu.** Ustawienie progu po cichu osłabiło test
`test_every_edge_from_a_bulk_import_has_provenance`, który asertował
`report.ok` — z progiem 733 przeszedłby nawet przy całkowicie zepsutym
pochodzeniu. Zamienione na porównanie liczby naruszeń do zera. Próg w kontroli
i asercja w teście to dwie różne rzeczy i łatwo je pomylić.

**22 encje z dwoma LEI-ami — kontrola była zła, nie dane.** Podejrzewałem błąd
scalania. Sprawdzenie w GLEIF pokazało coś innego:

* **P.S. TRADING** — jeden z dwóch rekordów GLEIF oznacza **wprost jako
  `DUPLICATE`**.
* **AVNET** — jeden LEI `LAPSED` pod dawną nazwą, drugi `ISSUED` pod obecną
  (TD SYNNEX AS POLAND). Ta sama spółka po zmianie nazwy.

Każda z 22 encji ma **jeden** KRS/NIP/REGON i dwa LEI-e, czyli scalenie poszło
po twardym identyfikatorze krajowym — dokładnie tak, jak wymaga N4. Błąd był
w kontroli: założyłem, że identyfikator jest jeden na encję w każdym schemacie,
a LEI tego nie gwarantuje. Kontrola obejmuje teraz wyłącznie `nip`, `krs`
i `regon`, a wyłączenie LEI ma własny test, żeby nikt go nie cofnął.

Skutek uboczny wart odnotowania: **wygasły LEI pod dawną nazwą jest śladem
historii nazwy** dla spółek z GLEIF. Nie wykorzystujemy go, ale jest.

---

## 2026-08-31 — Asercje jakości danych

**Skąd się wzięło.** Przegląd warstwy ETL pod kątem narzędzi, które mogłyby ją
uprościć. Wniosek był odwrotny do pytania: narzędzia nie były potrzebne, brakowało
czegoś innego. Dwie największe awarie w historii projektu — 69 438 fałszywie
scalonych firm i jedna działalność z 734 adresami — leżały w bazie tygodniami
i wyszły dopiero wtedy, gdy właściciel projektu wyszukał w interfejsie samego
siebie i zobaczył cudzy NIP. Obie były wykrywalne jednym zapytaniem SQL.

**Decyzja.** Zamiast orkiestratora (Airflow, Dagster) albo frameworku ładowania
(dlt) — zestaw asercji SQL uruchamianych po imporcie. Każda wywodzi się z awarii,
która naprawdę się zdarzyła, albo z niezmiennika z CLAUDE.md. Świadomie **nie**
dopisujemy asercji hipotetycznych: kontrola, która nigdy nie może zapłonąć, uczy
ignorowania raportu.

**Czego się nie spodziewałem — 1.** Napisałem kontrole na pętle własne
i na odwrócony okres obowiązywania, bo obie były realnymi awariami. Test
integracyjny nie dał ich zapalić: baza wymusza jedno i drugie ograniczeniem
`CHECK` (`ck_relationships_no_self_loop`, `ck_relationships_valid_period`).
Obie usunąłem, a powód zapisałem w module, żeby ktoś ich nie dopisał ponownie.
Warto odnotować, że wyszło to **tylko dlatego**, że każdy test sadzi konkretne
naruszenie zamiast sprawdzać czystą bazę.

**Czego się nie spodziewałem — 2 (poważne).** Pierwsze uruchomienie na
produkcyjnych danych: **6 392 682 z 6 466 459 krawędzi nie ma pochodzenia**.
To 98,9% grafu i złamanie niezmiennika N2 — „każda krawędź ma pochodzenie" —
czyli obietnicy, na której stoi cały produkt. Rozkład:

| typ krawędzi | wszystkie | bez źródła | źródło |
|---|---:|---:|---|
| `sole_proprietor_of` | 3 552 790 | 3 552 790 | CEIDG |
| `registered_at` | 2 892 240 | 2 839 892 | CEIDG |
| `parent_of` | 21 306 | **0** | GLEIF |
| `contractor_of` | 123 | **0** | BZP |

**Sprostowanie do pierwszej wersji tego wpisu.** Napisałem, że GLEIF i BZP
pomijają pochodzenie tak samo jak CEIDG. To była nieprawda — źle odczytałem
kolumny w zapytaniu diagnostycznym. GLEIF i BZP zapisują pochodzenie komplet,
przez `load_document`. Cały defekt siedzi w imporcie masowym CEIDG, który pisze
relacje zbiorczym SQL-em i nigdy nie dotyka `relationship_sources`. Zostawiam
pomyłkę w zapisie, bo wysłałaby kogoś do naprawiania kodu, który działa.

W bazie jest 341 dokumentów źródłowych i 77 004 wpisy pochodzenia na 6,47 mln
krawędzi.

**Co z tego wynika.** To nie jest usterka kosmetyczna. Bez pochodzenia nie da
się ani zweryfikować twierdzenia, ani obronić go przed osobą, której dotyczy —
a przy danych o firmach i ludziach to jest wymóg, nie ozdobnik. Naprawa wchodzi
na listę jako pilna, przed mapą i przed KRS.

**Czego nie zrobiłem.** Nie wpiąłem `check-data` w `make check`. Kontrole
wymagają bazy, a bramka, która dziś świeci na czerwono z powodu znanego długu,
przestaje cokolwiek znaczyć po tygodniu. Wpięcie po naprawie N2.

---

## 2026-08-31 — PRG i geokodowanie masowe

**Objaw.** Mapa zbiorcza podmiotów wymaga współrzędnych dla 2,4 mln adresów.
Nominatim dopuszcza jedno zapytanie na sekundę, co daje 28 dni odpytywania
cudzej infrastruktury. To nie jest droga.

**Co sprawdzono.** PRG (Państwowy Rejestr Granic) publikuje ~7 mln punktów
adresowych jako plik 1,79 GB, bezpłatnie i do dowolnego wykorzystania, także
komercyjnego. Przy okazji znalazł się rządowy geokoder GUGiK
(`services.gugik.gov.pl/uug`), którego nie było w planie: 35 trafień na 40
prawdziwych adresów z naszej bazy, 0 błędów, i zwraca **TERYT, SIMC i ULIC**
obok współrzędnych. Kolumna `addresses.teryt` istnieje i stoi pusta.

**Pułapki zapisane, żeby nie tracić na nie czasu drugi raz.**

* Serwer PRG **ignoruje nagłówek `Range`**. Poprosiłem o ostatnie 200 KB, żeby
  podejrzeć zawartość archiwum, i dostałem 540 MB strumienia. Pobranie musi być
  jednorazowe i całościowe — wznawianie odpada.
* Format zapytania do UUG to `Miasto, Ulica Numer`. Przecinek po mieście jest
  obowiązkowy; bez niego usługa zwraca zero wyników zamiast błędu.
* DuckDB z rozszerzeniem spatial czyta shapefile i GML, ale `ST_Transform`
  bez `always_xy := true` bierze urzędową kolejność osi EPSG:2180 i daje punkt
  **300 km w bok** — nadal w Polsce, więc błąd przechodzi przez każdy test,
  który nie sprawdza konkretnego punktu.

**Decyzja.** PRG masowo przez DuckDB (bez zależności systemowych — GDAL-a ani
PostGIS-a nie ma w tej instalacji i nie trzeba ich instalować), UUG na żądanie
dla reszty i dla uzupełnienia TERYT. Warunkiem wstępnym jest reimport CEIDG,
bo kolumna `building` jest pusta i nie ma czego dopasowywać.

---

## 2026-08-31 — Ranking wyszukiwarki

**Objaw zgłoszony przez użytkownika.** „ORLEN" zwracało jednoosobową
działalność „Orlena Hintzke" przed ORLEN S.A.

**Diagnoza.** Jedno zapytanie `LIKE 'orlen%'` sortowane po `entities.degree`.
Dwa niezależne defekty w jednej linijce. Po pierwsze, dla prefiksu „orlena" jest
nieodróżnialne od „orlen". Po drugie — i to jest ważniejsze — **stopień węzła nie
mierzy znaczenia podmiotu**, tylko ile krawędzi zdążyliśmy zaimportować. ORLEN
ma u nas jedno powiązanie, bo mamy z niego jedno źródło. To artefakt postępu ETL.

**Decyzja.** Trzy etapy prefiksowe: dokładny → do granicy słowa → dowolny.
Rozwiązanie strukturalne zamiast dobierania wag — „orlena" nie może wyprzedzić
„orlen termika", bo trafia do etapu późniejszego. Trafność w obrębie etapu łączy
pokrycie nazwy, obecność KRS, status i nasycony stopień.

**Koszt, którego nie przewidziałem.** `ORDER BY score` zmusza bazę do policzenia
trafności dla **każdego** trafienia — dla prefiksu „a" to 830 tys. wierszy.
Ranking najpierw zabił wydajność: 2377 ms. Naprawione ograniczeniem puli
kandydatów w podzapytaniu, które idzie po indeksie i kończy po znalezieniu
kompletu. Cena: w etapie ostatnim podmiot o niskim stopniu może wypaść z puli
przed rankingiem. Akceptowalna, bo trafienia dokładne mają wcześniejsze etapy.

**Znalezione po drodze.** Indeks GiST na `normalized_name` zajmował **2,1 GB**
— najwięcej w bazie — był użyty 26 razy (wyłącznie w moich pomiarach) i planer
wybierał go do zwykłej równości, zamieniając 0,2 ms na 555 ms. Powstał pod
wyszukiwanie KNN, które zmierzono na 2,9 s i porzucono. Usunięty migracją 0005.

**Wynik.** ORLEN 2377 ms → 2 ms, Skanska 1408 ms → 4 ms, prefiks „a" 802 ms →
27 ms. „PKN ORLEN" dawało zero wyników, bo nie jest prefiksem żadnej nazwy;
trigram spadł po usunięciu GiST do 140–250 ms i włącza się teraz automatycznie,
gdy tańsze etapy nic nie znalazły.

---

## 2026-08-31 — Fixture KRS opisywał API, które nie istnieje

**Objaw.** Trzy testy mappera KRS na czerwono po przepisaniu mappera pod
prawdziwy odpis.

**Co się okazało.** Fixture był **wymyślony**: z niezamaskowanymi nazwiskami
wspólników i zarządu oraz z `naglowekA` wewnątrz `dane`. Publiczne API KRS nie
ma ani jednego, ani drugiego. Testy przechodziły, opisując interfejs, którego
ministerstwo nigdy nie wystawiło — a to jest gorsze niż brak testu, bo czyta się
jak pokrycie.

**Decyzja.** Pobrany jeden prawdziwy odpis pełny (KRS 0000028860, 419 KB, 786
pól zamaskowanych u źródła łącznie z PESEL-em) i zamrożony jako fixture. Testy
sprawdzają teraz rzeczywiste gwarancje, w tym tę najważniejszą: **z KRS nigdy
nie powstaje encja osoby**, bo nazwiska są zamaskowane do pierwszej litery.

**Skutek uboczny.** Odpis pokazał, że zawiera **KRS i NIP naraz** — co jest
legalną podstawą scalenia duplikatów typu „ORLEN S.A. dwa razy" w rozumieniu
niezmiennika N4. Podniosło to priorytet wpięcia KRS.
