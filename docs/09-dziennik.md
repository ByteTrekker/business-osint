# Dziennik działań

Chronologiczny zapis tego, **co zrobiono i z czego to wynikło**. Nie jest to
lista zmian — od tego jest `git log`. Tutaj trafia droga: jaki był objaw, co
pomiar pokazał, jaką decyzję podjęto i czego ta decyzja kosztowała.

Zasada: wpis powstaje wtedy, gdy coś **zaskoczyło**. Zadanie wykonane zgodnie
z planem nie potrzebuje wpisu; wystarczy commit. Wpis jest po to, żeby za pół
roku dało się odtworzyć rozumowanie, którego nie widać w kodzie.

Kolejność odwrotna — najnowsze na górze.

---

## 2026-08-31 — PRG wczytane, i fałszywe dopasowanie złapane w porę

**Wynik.** 8 615 528 punktów adresowych z szesnastu plików GML. **1 946 032
adresy dostały współrzędne — 82% tych, które w ogóle da się dopasować.**
Przy okazji 1 946 195 dostało TERYT, czyli urzędowy identyfikator gminy,
którego rejestry przedsiębiorców nie podają wcale.

Kontrola poprawności, która przekonuje bardziej niż sam odsetek: średnie
współrzędne w każdym województwie trafiają w jego środek. Śląskie 50,24/18,94,
mazowieckie 52,23/21,02, wielkopolskie 52,27/17,17. Gdyby dopasowanie było
losowe, te liczby byłyby nieodróżnialne od siebie.

**Format okazał się inny, niż zakładałem.** PRG rozdziela adres na trzy obiekty:
punkt niesie numer i współrzędne, a nazwę miejscowości i ulicy trzyma jako
**referencje `xlink`** do osobnych elementów. To unieważniło plan z DuckDB —
czyta GML, ale `xlink` zostawia nierozwiązany, a w tym właśnie tkwi cała
trudność. Parser jest własny, strumieniowy, dwuprzebiegowy.

**Kolejność osi: pułapka, przed którą sam się ostrzegałem, i o mało w nią nie
wszedłem.** Plik deklaruje `EPSG:2180`, którego urzędowa kolejność to
(northing, easting), ale zapisuje odwrotnie. Chyrzyno odczytane zgodnie ze
specyfikacją ląduje w Małopolsce — 350 km dalej, **nadal w Polsce**, więc żadne
sprawdzenie „czy punkt jest w kraju" tego nie łapie. Rozstrzygnął dopiero pomiar
na znanym punkcie.

**Błąd, który wyglądał na sukces.** Pierwsza wersja dopasowywała po
`miejscowość|ulica|numer`. Wynik: 61 088 adresów ze współrzędnymi z jednego
województwa — wyglądało świetnie. Sprawdzenie, **skąd** pochodzą, pokazało
**7 459 fałszywych**: „Buczków, małopolskie" dostał punkt z lubuskiego, 400 km
dalej. Nazwy wsi powtarzają się między województwami.

Gdybym puścił wszystkie pliki bez tego sprawdzenia, byłoby to zapisane
w setkach tysięcy adresów, a każdy wyglądałby na poprawnie zgeokodowany. To ta
sama klasa błędu co N4: scalanie na niewystarczającej podstawie.

Naprawa: województwo z kodu TERYT jako warunek rozstrzygający. Jeden wyjątek,
uzasadniony — klucz występujący w kraju **raz** dopasowujemy bez tego warunku,
bo brak województwa po naszej stronie to niewiedza, nie sprzeczność. Po
poprawce na lubuskim: 87,2% trafień, **zero fałszywych**.

**Wniosek procesowy.** Odsetek trafień nie jest miarą poprawności. Pierwsza,
błędna wersja miała **wyższy** odsetek niż druga — bo dopasowywała także to,
czego nie powinna.

---

## 2026-08-31 — Dziennik zmian, i schemat testowy różny od produkcyjnego

**Po co.** Monitoring zmian jest tym, czego konkurencja ma najwięcej, a my nie
mieliśmy wcale. Pilność brała się z jednej rzeczy: **status, forma prawna,
kapitał i nazwa są nadpisywane w miejscu**, więc każdy import bez dziennika
kasował poprzednią wartość bezpowrotnie.

**Zakres celowo wąski.** Logujemy wyłącznie pola nadpisywane w miejscu. Relacje
są bitemporalne, więc ich historia jest odtwarzalna z `recorded_at`
i `superseded_at`; dublowanie jej w dzienniku podwoiłoby zapis przy imporcie
3,5 mln krawędzi i nie dołożyło ani jednej informacji. Kanał zmian scala oba
źródła **dopiero przy odczycie**.

**Wyzwalacze bazy, nie kod aplikacji.** Do `companies` i `entities` pisze ORM,
zbiorczy SQL importu CEIDG i wzbogacanie z KRS. Wpięcie się w każdą ścieżkę
z osobna oznaczałoby, że następna dopisana po cichu przestanie logować. Jest
test, który celowo używa zbiorczego `UPDATE ... FROM`, żeby nikt nie przeniósł
logowania do warstwy aplikacji.

**Znalezione przy okazji, i większe od samej funkcji.** Testy dziennika padły,
bo baza testowa powstawała przez `Base.metadata.create_all`. Tworzy on tabele
i indeksy, ale **nie wyzwalacze ani widoki** — te istnieją tylko w migracjach.
Schemat testowy różnił się więc od produkcyjnego, a conftest nadrabiał to,
przepisując widok `graph_edges` ręcznie: druga definicja tego samego obiektu.
To ta sama klasa błędu co przy normalizacji adresów i przy fixture KRS.

Baza testowa idzie teraz przez `alembic upgrade head`. Testy działają na tym
samym schemacie co produkcja i cała klasa cichego rozjazdu znika.

**Dwie pułapki po drodze.**

* `now()` w PostgreSQL zwraca czas **rozpoczęcia transakcji**, więc wszystkie
  zmiany z jednego importu mają identyczny znacznik. To użyteczne — widać, co
  przyszło razem — ale nie porządkuje ich między sobą; remis rozstrzyga rosnący
  klucz dziennika.
* Izolacja testów przez wycofanie transakcji ukrywa zapisy przed **innymi
  połączeniami**. Testy kolejki zadań sprawdzają `SKIP LOCKED` między dwoma
  workerami i przestały działać. Sprzątanie idzie przez `TRUNCATE`.

**Ograniczenie, które trzeba powiedzieć wprost.** Dziennik zaczyna się w dniu
wdrożenia. Zmian sprzed niego nie da się odzyskać — i to była cała pilność.

---

## 2026-08-31 — Co piąty przedsiębiorca nie ma w CEIDG adresu

**Pytanie brzmiało: czy da się ukryć adres w CEIDG.** Odpowiedziałem trzy razy
i dopiero trzecia odpowiedź była poparta pomiarem właściwej rzeczy.

1. „Tak, 675 tys. wpisów bez adresu" — liczba policzona na dwóch zbiorach,
   które nie są rozłączne. Wyszła blisko prawdy przez przypadek.
2. „To nasz błąd, nie rejestr" — sprawdziłem raport małopolskiego, zobaczyłem
   0,002% pustych adresów i orzekłem stanowczo. **Zły raport.**
3. Właściwy pomiar: CEIDG publikuje **siedemnaście** raportów, nie szesnaście.
   Siedemnasty nazywa się „Zarejestrowane działalności - brak województwa"
   i ma **714 771 wierszy, z czego 713 144 (99,8%) bez ani jednego pola adresu**.

**Dlaczego drugi pomiar mylił.** W raportach wojewódzkich adres ma praktycznie
każdy, bo **przypisanie do województwa bierze się właśnie z adresu**. Wpisy bez
adresu nie mają jak trafić do żadnego z szesnastu i lądują w siedemnastym.
Sprawdzenie jednego województwa nie mogło tego pokazać.

**Podstawa prawna.** Adres do doręczeń jest obowiązkowy, ale stałe miejsce
wykonywania działalności — tylko jeżeli przedsiębiorca takie miejsce **ma**.
W formularzu CEIDG-1 zaznacza się „brak stałego miejsca" i wtedy w rejestrze
jest adnotacja zamiast adresu. To nie jest obejście przepisu, tylko przewidziany
przypadek dla pracujących mobilnie.

**Co z tego wynika dla produktu.**

* **Mapa zbiorcza nigdy nie pokaże 20% firm.** To nie jest luka do uzupełnienia
  z PRG — tam nie ma czego geokodować. Trzeba to napisać przy mapie, inaczej
  będzie wyglądać na kompletną.
* Raport zawiera **3 328 wpisów oznaczonych jako „działalność prowadzona
  wyłącznie w formie spółki cywilnej"**. Spółki cywilne to jedyna droga do
  prawdziwej warstwy powiązań między osobami w CEIDG, a my tego pola nie czytamy.
* Przy każdej analizie regionalnej te 714 tys. wypada z zestawienia **po cichu**.

---

## 2026-08-31 — Test scalił 12 665 encji w bazie produkcyjnej

**Co się stało.** Test integracyjny scalania adresów wywołał
`merge_duplicate_addresses()`. Ta funkcja otwiera własną sesję na **silniku
ETL**, a więc na bazie `osint`, nie na testowej `osint_test`. Fixture
`db_session` nie ma jak jej przechwycić. Test przeszedł przez całą produkcyjną
bazę: **12 011 grup, 12 665 encji, 14 130 krawędzi.**

**Stan po zdarzeniu.** Wszystkie siedem kontroli jakości przechodzi. N2 dalej
pokazuje 733 krawędzie bez pochodzenia — dokładnie tyle co przed operacją,
czyli pochodzenie przeniosło się poprawnie. Encje scalone nie trzymają
aktywnych krawędzi. Każde scalenie ma wpis w `entity_merges` z uzasadnieniem,
więc operacja jest odwracalna.

**Dlaczego to jest poważne mimo poprawnego wyniku.** Operacja, którą dopiero
pisałem, wykonała się na pełnych danych **zanim ktokolwiek o to poprosił**
i zanim miała choć jeden przechodzący test. Skończyło się dobrze, ale to jest
kwestia szczęścia, nie procesu: gdyby SQL przenoszący krawędzie miał błąd,
dowiedziałbym się o tym po fakcie na 6,5 mln krawędzi.

**To trzeci raz ta sama pułapka.** `recompute_degrees` i `run_checks` też
otwierają własną sesję na silniku ETL; przy obu rozwiązałem to doraźnie —
raz testem sterującym instrukcjami wprost, raz wariantem `execute_checks`
przyjmującym sesję. Nie zapisałem reguły, więc trzeci raz wszedłem w to samo.

**Reguła, teraz zapisana w CLAUDE.md.** Każda funkcja korzystająca
z `get_etl_sessionmaker()` musi mieć wariant przyjmujący sesję, a testy wołają
wyłącznie ten wariant. Tu jest nim `merge_batch`.

---

## 2026-08-31 — Pobranie PRG przerwane na 94% przez limit, który sam ustawiłem

**Co się stało.** `curl --max-time 5400` przerwał pobieranie po 90 minutach,
gdy na dysku było **1 687 984 033 z 1 790 077 530 bajtów**. Archiwum bez
katalogu centralnego jest bezużyteczne, a serwer GUGiK **ignoruje nagłówek
`Range`**, więc wznowienie nie istnieje — trzeba od zera. Około 1,7 GB ruchu
z cudzego serwera zmarnowane.

**To była moja pomyłka, i to podwójna.** Sam wcześniej zapisałem w tym dzienniku,
że serwer nie wspiera wznawiania i że pobranie musi być traktowane jako
wszystko-albo-nic. Mimo to ustawiłem limit czasu **krótszy niż zmierzone tempo
transferu**: 18 MB/min przy 1707 MB to ponad 95 minut, a limit wynosił 90.

**Wniosek na przyszłość, ogólniejszy niż ten jeden plik.** Przy transferze,
którego nie da się wznowić, limit czasu jest złym narzędziem — mierzy nie to,
co trzeba. Właściwy jest limit **prędkości**: przerwij, gdy transfer faktycznie
stanął (`--speed-limit` z `--speed-time`), a nie gdy minęła arbitralna godzina.
Limit czasu chroni przed zawieszeniem procesu; limit prędkości chroni przed
zawieszeniem i pozwala wolnemu, ale postępującemu pobraniu dobiec do końca.

---

## 2026-08-31 — Adresy: to nie normalizacja się rozjechała, tylko kolumny

**Trzy razy zmieniałem diagnozę, zanim napisałem kod.** Warto zapisać drogę,
bo każdy kolejny pomiar unieważniał poprzedni wniosek.

1. „ORLEN ma dwa adresy tej samej siedziby" — wygląda na rozjechaną
   normalizację napisu.
2. Zliczenie duplikatów po miejscowości, ulicy i numerze: **503 966 nadmiarowych
   wierszy**. Liczba nieprawdziwa — klucz pomijał numer lokalu, więc scalał
   różne mieszkania.
3. Po dołożeniu lokalu: **12 967**, z czego 12 302 różnią się kodem pocztowym.
   To wyglądało na „różne miejsca", więc prawie nic do naprawy.
4. Obejrzenie próbki: **Agatówka ma dwa kody pocztowe dla tego samego budynku**
   (37-450 i 37-464). Kod pocztowy nie należy do tożsamości adresu.
5. I dopiero spojrzenie na trzy encje ORLEN-u pokazało prawdziwą przyczynę:
   **kolumny znaczą co innego w każdym źródle.** GLEIF wrzucał całą linię
   `PŁOCK BIELSKA 67` do `street` i zostawiał `building` puste, KRS zapisywał
   `ul. Chemików` z przedrostkiem, CEIDG czysto.

**Właściwa naprawa okazała się prostsza od wszystkich rozważanych.** GLEIF podaje
numer budynku w osobnym polu `addressNumber` i numer lokalu w
`addressNumberWithinBuilding` — nasz mapper po prostu ich nie czytał. Nie trzeba
niczego zgadywać ani parsować heurystycznie.

**Czego nie zrobiłem i dlaczego.** Nie scalam 12 032 istniejących duplikatów.
To wymaga przeniesienia krawędzi przez `entity_merges` z zachowaniem N1 (fakty
niezmienne) i N2 (pochodzenie przenosi się razem z krawędzią) — osobna zmiana,
nie dopisek do poprawki mapperów. Dług jest policzony i pilnowany progiem
w kontroli jakości: 12 033. naruszenie oznacza, że mappery znowu się rozjechały.

**Sprostowanie.** Pisałem, że to blokuje PRG. Nie blokuje — dopasowanie do
punktów adresowych idzie wiersz po wierszu, więc duplikaty po prostu dostaną
współrzędne dwa razy. To poprawka jakości danych, nie warunek wstępny.

**Dwie pułapki po drodze.**

* Bramka mutacyjna złapała mnie natychmiast po tym, jak ją naprawiłem:
  zaimportowałem `format_address` z `etl/ceidg_pipeline` do mappera GLEIF,
  co wciągnęło warstwę bazy do piaskownicy mutmut. Funkcja jest czysta i jej
  miejsce było w `domain/` od początku. Naprawa bramki zwróciła się w godzinę.
* Ręczne zastosowanie mutacji do pliku, żeby sprawdzić, czy test ją wykrywa,
  zostawiło **nieaktualny bajtkod**. Kolejne uruchomienie pokazywało wynik
  zmutowany mimo przywróconego źródła, przez co przez chwilę uznałem poprawny
  test za błędny. `find src -name __pycache__ -exec rm -rf` przed pomiarem.

---

## 2026-08-31 — Szukanie po adresie: jedna wartość w dwóch sprzecznych rolach

**Diagnoza z poprzedniej tury się potwierdziła.** Adres pełnił dwie role
i dzielił dla nich jedną wartość:

* **klucz scalania** musi być sklejony, żeby „ul. Chemików 7" i „Chemików 7"
  trafiły w ten sam wiersz;
* **pole wyszukiwania** musi mieć spacje, bo indeks pełnotekstowy dzieli po
  słowach.

Te wymagania są sprzeczne, więc jedna wartość nie mogła spełnić obu. Wygrał
klucz scalania i przez to adresu nie dało się wyszukać **w ogóle**.

**Decyzja.** Dwie nazwane funkcje domenowe zamiast jednej: `address_natural_key`
(sklejony, do `addresses.normalized`) i `address_search_key` (ze spacjami, do
`entities.normalized_name`). Osobny test pilnuje, żeby ktoś ich nie „uprościł"
z powrotem do jednej — bo wyglądają na duplikat, a nie są.

**Naprawa 2,4 mln wierszy — w Pythonie, nie w SQL-u.** Napisałem najpierw
wersję z `regexp_replace` i `translate` w SQL-u i ją wyrzuciłem: druga
implementacja tej samej reguły rozjechałaby się z pierwszą przy najbliższej
zmianie normalizacji, a wtedy część adresów byłaby wyszukiwalna inaczej niż
reszta, bez żadnego sygnału. Partiami po 20 tys., z użyciem funkcji domenowej.

**Pętla nieskończona, którą złapałem przed uruchomieniem.** Pierwsza wersja
wybierała partie warunkiem „nazwa bez spacji" — wygląda naturalnie i nigdy się
nie kończy: adres jednowyrazowy po przeliczeniu **nadal** nie ma spacji, więc
wracałby w każdej kolejnej partii. Postęp śledzi teraz kursor po `id`.
Po naprawie 216 z 2 421 739 adresów nadal nie ma spacji i to jest poprawne —
to nazwy jednowyrazowe.

**Usunięte kruche złączenie.** Import CEIDG łączył encję adresu z wierszem po
`entities.normalized_name = address_normalized`. Działało wyłącznie dopóki oba
pola trzymały tę samą wartość, czyli dokładnie dopóki istniał opisywany defekt.
Identyfikator adresu wędruje teraz przez tabelę pomocniczą, tak samo jak
identyfikatory firmy i właściciela.

**Wynik na prawdziwych danych.** „chemikow plock" → 6 ms, „konrada leczkowa
gdansk" → 17 ms, „plock chemikow" → 4 ms. Wcześniej: zero wyników, niezależnie
od zapytania.

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

---

## 2026-09-01 — Mapa: agregacja, która nie zależy od zapytania

**Objaw.** Pierwsza działająca wersja mapy zbiorczej odpowiadała 1,8 s na jedno
przesunięcie widoku. Mapa, która myśli dwie sekundy przy każdym ruchu myszy,
nie jest mapą.

**Co pokazał plan.** Dwie rzeczy naraz. Złączenie z `entities` po stopień węzła
wymuszało skan 9,5 mln wierszy. I grupowanie po wyrażeniu `round(latitude/:cell)`
było dla planisty nieprzejrzyste — szacował 356 tys. grup przy 723
rzeczywistych, więc zamiast agregacji mieszającej wybierał sortowanie ze
zrzutem 17 MB na dysk. Indeks częściowy na współrzędnych (migracja 0010) zbił
sam skan adresów ze 134 ms do 54 ms, ale reszty nie ruszał.

**Obserwacja, która rozwiązała problem.** Ta agregacja **nie zależy od
zapytania**. Siatka jest stała, dane zmieniają się tylko przy imporcie.
Liczenie jej przy każdym przesunięciu myszy to powtarzanie tej samej pracy —
nie problem wydajności zapytania, tylko zła pora na jego wykonanie.

**Rozwiązanie.** Jeden przeliczony poziom (`address_cells`, 297 246 komórek po
0,005 stopnia, 4,7 s przeliczenia), a zgrubniejsze poziomy zwijane z niego
w locie. Zwijanie jest dokładne pod jednym warunkiem: każdy bok komórki musi
być całkowitą wielokrotnością komórki bazowej, a binowanie musi iść przez
`floor`, nie `round` — `floor(floor(x/f)/k)` równa się `floor(x/(f*k))`, przy
`round` ta równość nie zachodzi.

**Wynik.** Cały kraj 1821 → 154 ms, województwo 852 → 38 ms, Warszawa → 18 ms.

**Trzy rzeczy, które kosztowały osobno.**

*Metadane na ścieżce gorącej.* Liczba adresów bez współrzędnych to skan 2,4 mln
wierszy, 108 ms — doliczany do **każdego** przesunięcia widoku, choć zmienia się
wyłącznie przy imporcie. Osobny punkt końcowy `/map/coverage`, wołany raz.

*Promień w pikselach, nie w wartościach bezwzględnych.* Pierwsza wersja skalowała
promień pierwiastkiem z licznika do 34 px. Przy widoku całego kraju komórka
0,25 stopnia ma na ekranie kilkanaście pikseli — koła zlały się w jednolitą
niebieską plamę w kształcie Polski. Ten sam licznik znaczy inną gęstość na
każdym poziomie, więc maksymalny promień musi wynikać z **ekranowego** rozmiaru
komórki.

*Asynchroniczne tworzenie mapy nie paruje się ze sprzątaniem.* `await
import("leaflet")` wewnątrz efektu Reacta oznacza, że tworzenie jest
asynchroniczne, a sprzątanie synchroniczne. Przy podwójnym montowaniu na jednym
kontenerze powstawała druga, osierocona instancja: dublowała żądania (widoczne
w logu sieci jako dwa prostokąty różniące się o 0,025 stopnia — dwie różne
wysokości kontenera) i przestawała reagować na kliknięcia. Leaflet ładowany
przez stan komponentu, mapa tworzona synchronicznie.

**Czego się nauczyłem o weryfikacji.** Trzy razy odczytałem stan strony
w trakcie animacji Leafleta i trzy razy wyciągnąłem fałszywy wniosek — raz
„brak znaczników", raz „zero po przybliżeniu", raz „zapytanie nie poszło".
Za każdym razem drugi odczyt kilka sekund później pokazywał stan poprawny.
Zrzut ekranu i odczyt DOM w trakcie przejścia to **pomiar w połowie operacji**,
a nie obserwacja wyniku.

**Reguła siatki wylądowała w `domain/`.** Warunek „bok komórki jest całkowitą
wielokrotnością komórki bazowej" nie potrzebuje bazy, a jego złamanie jest
dokładnie tą klasą błędu, o którą chodzi w testach mutacyjnych: mapa nadal
rysuje, liczby przestają się sumować, nic nie zgłasza błędu. Bramka mutacyjna
od razu wykazała, że wyjątek z pustym komunikatem przechodzi mój test — bo
sprawdzał tylko typ wyjątku, nie to, czy komunikat nazywa błędną wartość.
