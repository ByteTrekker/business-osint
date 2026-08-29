# Założenia projektu

Dokument źródłowy dla wszystkich pozostałych. Jeżeli coś w kodzie przeczy temu
dokumentowi — błąd jest w kodzie albo dokument wymaga świadomej zmiany, nie
cichego obejścia.

## 1. Problem

Rejestry publiczne w Polsce udostępniają **dokumenty**, nie **relacje**. Odpis
z KRS odpowiada na pytanie „co jest wpisane o tej spółce”. Nie odpowiada na
pytanie, które w praktyce zadaje analityk, dziennikarz i dział compliance:

> Jak ta firma jest powiązana z innymi firmami i osobami w polskiej gospodarce?

Odpowiedź wymaga przejścia przez kilka odpisów, ręcznego dopasowania osób po
imieniu i nazwisku oraz zapamiętania, co się widziało. Jest to praca, którą da
się zautomatyzować, i której nikt nie wykonuje ręcznie dwa razy.

## 2. Teza produktu

Warstwa relacyjna zbudowana ponad rejestrami publicznymi ma wartość niezależną
od samych rejestrów. Jednostką wyniku jest **węzeł w grafie**, nie dokument.

Trzy własności, które odróżniają ten produkt od wyszukiwarki KRS:

1. **Eksploracja** — klikanie kolejnych węzłów zamiast otwierania kolejnych odpisów.
2. **Czas** — stan powiązań na dowolny dzień, nie tylko na dziś.
3. **Pochodzenie** — przy każdej relacji widać, z jakiego dokumentu wynika.

## 3. Dla kogo

| segment | zadanie, które wykonują | co ich przekonuje |
|---|---|---|
| due diligence / M&A | sprawdzenie kontrahenta przed transakcją | historia powiązań, provenance |
| compliance / AML | weryfikacja beneficjentów i powiązań osobowych | CRBR, alerty o zmianach |
| dziennikarstwo śledcze | znalezienie ukrytego powiązania | ścieżki między podmiotami, adresy |
| analiza zamówień publicznych | wykrycie powiązanych oferentów | przetargi + graf |
| sprzedaż / research B2B | zmapowanie grupy kapitałowej | struktura właścicielska |

Segment, na którym skupiamy się jako pierwszym: **due diligence i compliance** —
mają budżet, powtarzalną potrzebę i wymagają dokładnie tego, co jest najtrudniejsze
technicznie (provenance i historia). Zbudowanie produktu pod nich daje za darmo
funkcje dla pozostałych.

## 4. Zakres MVP

**Wchodzi:**

- wyszukiwanie podmiotu po nazwie, NIP, KRS, REGON
- profil podmiotu z identyfikatorami i listą powiązań
- profil osoby z listą jej podmiotów
- interaktywny graf powiązań z eksploracją przez kliknięcie
- relacje: zarząd, rada nadzorcza, wspólnicy, udziałowcy, prokura, adres siedziby,
  podmiot dominujący
- historia powiązań (data od / data do) i widok „stan na dzień”
- źródło przy każdej relacji

**Nie wchodzi — świadomie:**

| pomijamy w MVP | powód |
|---|---|
| beneficjenci rzeczywiści (CRBR) | osobne źródło, osobny format — kwartał 2 |
| sprawozdania finansowe | XML/PDF z eKRS, bardzo wysoki koszt parsowania |
| zamówienia publiczne i dotacje | wartościowe, ale wymagają działającego entity resolution |
| alerty i monitoring | wymagają stabilnego importu przyrostowego |
| konta użytkowników i płatności | brak sensu przed potwierdzeniem, że ktoś tego chce |
| scoring ryzyka | interpretacja danych, zanim dane są kompletne, produkuje fałszywe wnioski |

Reguła porządkująca: **najpierw kompletny pionowy przekrój na małych danych,
potem skala.** Import całego KRS to problem czasu i cierpliwości. Entity resolution
to problem projektowy — i tam kryje się całe ryzyko projektu.

## 5. Założenia o danych

1. **Wyłącznie źródła oficjalne lub otwarte.** Żadnego scrapowania komercyjnych
   agregatorów — ryzyko prawne i uzależnienie produktu od cudzej infrastruktury.
2. **Surowy dokument zapisujemy przed parsowaniem.** Zawsze, bez wyjątku.
3. **Opóźnienie względem rejestru ≤ 48 h** dla podmiotów aktywnych.
4. **Dane osobowe w minimalnym zakresie**: imię, nazwisko, rocznik (tylko gdy
   potrzebny do rozróżnienia imienników). PESEL nigdy jawnie — wyłącznie hash
   z pepperem. Adresy zamieszkania osób fizycznych — nie pobieramy.
5. **Dane bywają błędne u źródła.** Korekta jest osobnym faktem z własnym
   źródłem, nigdy nadpisaniem oryginału.

## 6. Niezmienniki techniczne

Cztery reguły, których naruszenie jest defektem krytycznym, a nie kwestią stylu.
Wszystkie mają pokrycie w testach.

### N1. Fakty są niezmienne

Żadnego `UPDATE` na relacji i żadnego `DELETE`. Zmiana faktu to zamknięcie
starego wiersza (`superseded_at`) i wstawienie nowego. Powód: rejestry zmieniają
dane wstecz, a produkt do due diligence musi umieć wykazać, co pokazywał
w konkretnym dniu.

### N2. Każda krawędź ma pochodzenie

Relacja bez wpisu w `relationship_sources` to błąd loadera, nie stan dopuszczalny.
Wskaźnik `locator` prowadzi do konkretnego miejsca w dokumencie, nie tylko do
nazwy rejestru.

### N3. Budżet zapytania jest częścią kontraktu API

Każda odpowiedź grafowa zawiera `meta.truncated`. Ciche przycięcie wyniku
w narzędziu do compliance to defekt krytyczny — użytkownik podejmuje decyzje
na podstawie tego, czego **nie** widzi.

### N4. Zbieżność imienia i nazwiska nie jest dowodem tożsamości

Automatyczne scalenie osób wymaga twardego identyfikatora albo co najmniej dwóch
niezależnych sygnałów. Wynik pośredni idzie do kolejki przeglądu. Każde scalenie
jest odwracalne. Powód: fałszywe powiązanie w narzędziu due diligence powoduje
realną szkodę u osoby trzeciej.

## 7. Założenia architektoniczne

| założenie | uzasadnienie |
|---|---|
| jedna baza (PostgreSQL), graf relacyjnie | ADR-0001 — skala nie wymaga bazy grafowej |
| modularny monolit | jeden model danych, jeden zespół |
| REST, nie GraphQL | ADR-0004 — trzy kształty odpowiedzi, budżet jako parametr |
| bitemporalność od pierwszego dnia | ADR-0003 — dopisanie wstecz oznacza utratę historii |
| ORM do zapisu, surowy SQL do odczytu grafu | traversal przez ORM to N+1 w pętli |
| logika domenowa bez I/O | testy jednostkowe w milisekundach, bez bazy |

## 8. Definicja ukończenia MVP

Wszystkie warunki muszą być spełnione jednocześnie:

- [ ] dowolna polska spółka z KRS jest wyszukiwalna po nazwie i po NIP
- [ ] jej profil pokazuje osoby z rolami i okresami pełnienia funkcji
- [ ] kliknięcie w osobę pokazuje jej pozostałe podmioty
- [ ] graf renderuje się dla podmiotu o 200 powiązaniach bez zawieszenia przeglądarki
- [ ] każda relacja ma widoczne źródło z datą pobrania
- [ ] „stan na dzień” działa dla dat wstecz
- [ ] dwóch różnych Janów Kowalskich to dwa węzły; ta sama Anna Nowak w trzech
      spółkach to jeden węzeł
- [ ] p95 dla `/graph/{id}?depth=2` poniżej 300 ms
- [ ] istnieje procedura sprostowania i sprzeciwu (RODO)

## 9. Metryki i progi alarmowe

| wskaźnik | próg | reakcja |
|---|---|---|
| p95 `/graph/{id}?depth=2` | > 300 ms | cache podgrafów, potem Apache AGE |
| odsetek odpowiedzi `truncated=true` | > 20% | budżety za ciasne albo huby źle obsłużone |
| kolejka przeglądu ER | rośnie szybciej niż maleje | progi scoringu za luźne |
| opóźnienie względem rejestru | > 48 h | import nie nadąża — patrz strategia wielojęzykowa |
| relacje bez provenance | > 0 | błąd loadera, wstrzymanie importu |
| czas pełnego przebiegu ER | > 2 h | próg przepisania ER do Rusta (ADR-0005) |

## 10. Ryzyka

| ryzyko | wpływ | mitygacja |
|---|---|---|
| **fałszywe scalenie osób** | krytyczny — szkoda u osoby trzeciej | N4, kolejka przeglądu, odwracalność, `entity_merges` |
| **API KRS bez SLA, blokada IP** | krytyczny — zatrzymanie projektu | rate limit 1 req/s, backoff, wznawialny import, `User-Agent` z kontaktem |
| **żądanie usunięcia danych (RODO)** | wysoki — prawny | flaga `suppressed_at`, procedura przed startem |
| **zmiana schematu API rejestru** | średni | mapper jako czysta funkcja z testem na zamrożonym fixture |
| **konkurencja (Rejestr.io i inni)** | wysoki — biznesowy | wyróżnik w historii, alertach i przetargach, nie w kompletności |
| **czas importu 8 dni** | średni | import przyrostowy i wznawialny od pierwszej wersji |

## 11. Założenia, które mogą się okazać fałszywe

Sekcja istnieje po to, żeby dokument był uczciwy. Przy każdym założeniu jest
warunek, który je obala.

| założenie | obala je |
|---|---|
| „PostgreSQL wystarczy do grafu” | p95 > 300 ms przy depth 2 mimo indeksów i cache |
| „reguły wystarczą do entity resolution” | > 30% par w kolejce przeglądu po strojeniu progów |
| „użytkownicy chcą grafu” | analityka pokazuje, że klikają w listę powiązań, a nie w graf |
| „due diligence zapłaci” | brak konwersji po 50 rozmowach z segmentem |
| „batch wystarczy do importu” | wymóg opóźnienia < 1 h zamiast < 48 h |
| „Python wystarczy do ETL” | przebieg ER > 2 h lub import poza oknem nocnym (ADR-0005) |

Każde z tych założeń jest testowalne. Żadne nie jest kwestią gustu.
