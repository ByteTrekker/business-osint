# Źródła danych

Zasada: **wyłącznie źródła oficjalne lub otwarte.** Żadnego scrapowania
komercyjnych agregatorów — to ryzyko prawne i uzależnienie produktu od cudzej
infrastruktury.

Ten dokument opisuje **stan faktyczny**, zmierzony 2026-09-01 na bazie
produkcyjnej, a nie plan. Czego brakuje — patrz „Zestawienie z listą rejestrów".

---

## Co mamy dzisiaj

| źródło | co z niego bierzemy | krawędzi w grafie | dokumentów |
|---|---|---|---|
| **CEIDG** `dane.biznes.gov.pl` | jednoosobowe działalności: osoba, firma, adres, PKD, status | 6 406 272 | 18 |
| **GLEIF** `api` + `goldencopy` | identyfikatory LEI, adresy, **powiązania spółka–spółka** | 76 887 | 293 |
| **BZP** `ezamowienia.gov.pl` | zamówienia publiczne, wykonawca ↔ zamawiający | 134 | 47 |
| **KRS** `api-krs.ms.gov.pl` | na żądanie, pojedyncze odpisy — KRS + NIP naraz | 1 | 1 |
| **wykaz CIT** (art. 27b) | podatek dochodowy dużych podatników | — | 3 |
| **PRG** GUGiK | punkty adresowe: współrzędne, TERYT, SIMC, ULIC | — | 8 615 528 punktów |

Stan grafu:

| | liczba |
|---|---|
| firmy | 3 600 791 |
| osoby | 3 552 821 |
| adresy | 2 409 074 |
| krawędzie `sole_proprietor_of` | 3 552 839 |
| krawędzie `registered_at` | 2 892 400 |
| krawędzie `parent_of` (GLEIF) | 21 306 |
| krawędzie `contractor_of` (BZP) | 124 |
| identyfikatory: NIP / LEI / KRS / REGON | 3 560 269 / 45 530 / 23 683 / 2 890 |
| sprawozdania finansowe | 6 990 |

---

## Najważniejsza rzecz w tym dokumencie: nasza warstwa osobowa jest pozorna

Osób w bazie jest 3 552 821. Wygląda to jak warstwa osobowa. Nie jest.

| ile firm przypada na jedną osobę | osób |
|---|---|
| 1 | 3 552 803 |
| 2 | 18 |

Zero osób występuje jako **cel** krawędzi. Zero powiązań osoba–osoba.

Każdy „człowiek" w naszej bazie to przedsiębiorca z CEIDG przypisany do
własnej, jedynej działalności. To nie jest graf — to zmiana etykiety na tym
samym wierzchołku. Pytanie „w ilu spółkach siedzi ta osoba", czyli to, po co
istnieje Rejestr.io, **nie ma dziś w tej bazie żadnej reprezentacji**.

I nie da się tego naprawić z KRS-u. Sprawdzone na żywo 2026-09-01, odpis
aktualny KRS 0000028860 przez publiczne API:

```
dzial2.reprezentacja.sklad[0].nazwisko.nazwiskoICzlon  = 'F*****'
dzial2.reprezentacja.sklad[0].imiona.imie              = 'I*******'
dzial2.reprezentacja.sklad[0].identyfikator.pesel      = '5**********'
```

79 pól zamaskowanych u źródła w jednym odpisie aktualnym; 786 w odpisie pełnym.
Maskowane są **imię, nazwisko i PESEL** członków zarządu, organu nadzoru
i prokurentów. Publiczne API KRS jest dla warstwy osobowej ślepą uliczką i nie
ma znaczenia, ile odpisów pobierzemy.

---

## Skąd zatem wziąć nazwiska — zestawienie dróg

Sprawdzone technicznie 2026-09-01. Kolumna „legalność" jest **pytaniem do
prawnika, nie odpowiedzią** — patrz [03-prawo-i-ryzyko.md](03-prawo-i-ryzyko.md).

| źródło | nazwiska | masowo? | stan sprawdzenia |
|---|---|---|---|
| **KRS API** | nie — zamaskowane wraz z PESEL-em | — | zweryfikowane na żywo, ślepa uliczka |
| **MSiG** | **tak, bez maskowania** | **tak — PDF-y od 1996** | pobrany numer 1/2026, patrz niżej |
| **CRBR** | tak — beneficjent + PESEL | nie ma eksportu zbiorczego | API publiczne, `POST /adcrbr/api/wyszukajSpolke` po NIP |
| **RDF** (sprawozdania) | częściowo — podpisy pod sprawozdaniem | po jednym podmiocie | dostęp bezpłatny |
| **Repozytorium Akt Rejestrowych** | tak — skany akt | po jednym podmiocie | dostęp bezpłatny |
| **CEIDG** | tak — i już je mamy | tak | jedyna dziś używana droga |

### MSiG jest technicznie otwarty i to zmienia obraz

`wyszukiwarka-msig.ms.gov.pl` udostępnia **każdy numer od 1996 roku** jako PDF
pod adresem `/api/Monitor/Download?id={id}&fileId=true`. Numery ważą 0,5–2 MB,
wychodzi około 250 numerów rocznie — rzędu 7 500 plików i kilku gigabajtów za
trzydzieści lat. To jest jedno popołudnie pobierania, nie osiem dni.

Pobrany numer 1/2026 (103 strony, 517 pozycji, 179 numerów KRS):

* **zero maskowania** — ani jednej gwiazdki w całym numerze,
* **36 numerów PESEL zapisanych jawnie**,
* pełne imiona i nazwiska przy postanowieniach sądu.

To jest dokładnie ta treść, którą KRS przez API zasłania. Nie dlatego, że MSiG
coś obchodzi — dlatego, że **publikacja wpisu w Monitorze jest ustawowym celem
tego wydawnictwa**, a maskowanie w API jest decyzją o formie udostępniania.

### Czego to jeszcze nie przesądza

1. **Publikacja w dzienniku urzędowym to nie to samo co pozwolenie na budowę
   wyszukiwarki.** Ponowne opublikowanie tych samych danych w bazie
   przeszukiwalnej po nazwisku jest **osobną operacją przetwarzania** w rozumieniu
   RODO i wymaga własnej podstawy prawnej. To jest ten sam spór, który
   przechodziły Rejestr.io i Bisnode. Bez opinii prawnika nie ruszamy.
2. **PESEL.** Numery są w Monitorze jawne, a nasza reguła jest twarda: PESEL
   nigdy jawnie, wyłącznie `pesel_hash()` z pepperem. Jeżeli MSiG wejdzie, PESEL
   ma być haszowany **na etapie parsowania**, zanim cokolwiek trafi na dysk —
   `raw_documents` też są dyskiem.
3. **Nie każda sekcja Monitora nas dotyczy.** Fragment, na którym potwierdziłem
   brak maskowania, to postanowienie upadłościowe **osoby fizycznej
   nieprowadzącej działalności gospodarczej** — kategoria najbardziej wrażliwa
   z możliwych i do grafu powiązań gospodarczych niepotrzebna. Zakres zbierania
   ma być zawężony do wpisów KRS, a nie „cały Monitor, bo się da".
4. **Parsowanie PDF-a to nie jest API.** Monitor jest składany typograficznie;
   struktura wpisu wynika z układu tekstu, nie ze schematu. Mapper będzie
   kruchszy niż wszystko, co mamy dzisiaj, i musi mieć zamrożone fixture'y na
   kilku rocznikach — układ zmieniał się przez trzydzieści lat.

### Rekomendacja

Kolejność, w której to ma sens robić:

1. **Spółki cywilne z CEIDG** (3 328 wpisów) — jedyne powiązanie osoba–osoba
   dostępne z danych, które już mamy, na już legalnej podstawie. Zero nowego
   ryzyka. Robimy najpierw, niezależnie od reszty.
2. **CRBR po NIP-ie, na żądanie** — jak dzisiejszy KRS: pojedyncze zapytanie
   przy oglądaniu podmiotu, bez budowania kopii rejestru. Daje beneficjenta
   rzeczywistego, czyli dokładnie to, czego w KRS nie ma.
3. **MSiG** — dopiero po opinii prawnej, z zakresem zawężonym do wpisów KRS
   i z haszowaniem PESEL-a przed zapisem. To jest jedyna znana droga do
   masowej warstwy `osoba → spółka`, więc warto o nią zapytać wprost.

---

## Zestawienie z listą rejestrów

| rejestr | rola | mamy? |
|---|---|---|
| **KRS** / Open API | rdzeń: spółki, KRS+NIP | na żądanie, bez warstwy osobowej |
| **CRBR** | rdzeń: beneficjenci rzeczywiści | nie |
| **REGON / BIR1** | rdzeń: pełna lista podmiotów, PKD | nie — 2 890 REGON-ów przypadkiem |
| **CEIDG** | rdzeń: jednoosobowe działalności | **tak, kompletnie** |
| **RDF** | finanse: sprawozdania | 6 990 z wykazu CIT, nie z RDF |
| **Repozytorium Akt Rejestrowych** | dokumenty źródłowe | nie |
| **MSiG** | zdarzenia: wpisy, zmiany | nie — patrz wyżej |
| **KRZ** | ryzyko: upadłości, zakazy | nie |
| **biała lista VAT** | status VAT, rachunki | nie |
| **UOKiK / KNF** | dodatki: koncentracje, zezwolenia | nie |
| **TERYT / GUS** | słownik administracyjny | **tak, przez PRG** |

Największa dziura to **REGON**. Nie z powodu treści — z powodu roli: BIR1 daje
listę numerów KRS, bez której nie wiadomo nawet, o co pytać KRS. Dziś nasze
23 683 numerów KRS pochodzą z GLEIF, czyli z próbki obciążonej w stronę dużych
podmiotów.

---

## Zasady wspólne dla wszystkich źródeł

1. **Surowy dokument zawsze przed parsowaniem** (`raw_documents` + sha256).
   Wyjątek: dane, których nie wolno nam trzymać jawnie (PESEL) — te są
   haszowane przed zapisem, także w surowym dokumencie.
2. **Dedup po treści** — niezmieniony dokument nie tworzy nowego snapshotu.
3. **Rate limit i backoff** — zablokowany adres IP zatrzymuje cały projekt.
4. **Mapper to czysta funkcja z testami na zamrożonym fixture** — zmiana schematu
   po stronie urzędu ma dawać czerwony test, nie cichy zanik danych w grafie.
   Fixture musi być **prawdziwy**: raz opisaliśmy w nim API KRS, którego
   ministerstwo nigdy nie wystawiło, i testy przechodziły.
5. **Każde źródło ma wpis w tabeli `sources`** z licencją i częstotliwością
   odświeżania.
6. **`User-Agent` z kontaktem** — jeżeli obciążacie cudze API, dajcie się namierzyć.

## Licencje

Dane z rejestrów publicznych są co do zasady dostępne do ponownego wykorzystania
(ustawa o otwartych danych), ale **warunki różnią się między rejestrami** —
niektóre wymagają wskazania źródła i daty pobrania. Dlatego `sources.license`
jest osobną kolumną, a interfejs pokazuje źródło przy każdej relacji. To nie jest
tylko zgodność z prawem: to jest funkcja produktu.

Osobno i ważniej: **licencja na dane to nie to samo co podstawa przetwarzania
danych osobowych.** Otwarta licencja na zbiór nie czyni legalnym zbudowania
z niego wyszukiwarki po nazwisku.
