# Dziennik działań

Chronologiczny zapis tego, **co zrobiono i z czego to wynikło**. Nie jest to
lista zmian — od tego jest `git log`. Tutaj trafia droga: jaki był objaw, co
pomiar pokazał, jaką decyzję podjęto i czego ta decyzja kosztowała.

Zasada: wpis powstaje wtedy, gdy coś **zaskoczyło**. Zadanie wykonane zgodnie
z planem nie potrzebuje wpisu; wystarczy commit. Wpis jest po to, żeby za pół
roku dało się odtworzyć rozumowanie, którego nie widać w kodzie.

Kolejność odwrotna — najnowsze na górze.

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
