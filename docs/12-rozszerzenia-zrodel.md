# Co jeszcze da się wyciągnąć z tych samych źródeł

Analiza dziesięciu źródeł: co już bierzemy, co ignorujemy, co jest warte
dobrania. Sprawdzone na kodzie i na żywych odpowiedziach 2026-09-02.
Czego nie potwierdziłem, jest oznaczone jako **niesprawdzone** — nie zgaduję.

---

## Najpierw: metadanych krawędzi nie trzeba dodawać

Wszystkie siedem pól, o które pytasz, **już jest w modelu**:

| pytane | gdzie leży |
|---|---|
| `source` | `raw_documents.source_id` → `sources.name` |
| `source_url` | `raw_documents.url` |
| `source_type` | `sources.kind` |
| `retrieved_at` | `raw_documents.fetched_at` |
| `valid_from` / `valid_to` | `relationships.valid_from` / `valid_to` |
| `confidence` | `relationships.confidence` + `confidence_score` |

Wiąże je `relationship_sources` (krawędź ↔ dokument ↔ `locator`, czyli miejsce
w dokumencie). To jest niezmiennik N2 i obowiązuje od początku. **Żadne z poniższych
rozszerzeń nie wymaga zmiany tej części modelu** — wymaga wypełnienia jej danymi.

---

## 1. KRS — największa niewykorzystana rezerwa

**Bierzemy dziś:** nazwę, formę prawną, KRS, NIP, REGON, adres siedziby,
kapitał zakładowy (wartość bieżącą), skład reprezentacji i wspólników
spółek z o.o. Nazwiska są u źródła zamaskowane, więc **nie powstaje z tego
ani jedna encja osoby**.

**Czego nie bierzemy** — sprawdzone na odpisie pełnym KRS 0000028860 (432 KB):

| co | ile w tym odpisie | wartość dla grafu |
|---|---|---|
| ~~`naglowekP.wpis` i `nrWpisuWprow/Wykr`~~ | — | **mapper już to ma** (`entry_dates`, `_period`) — patrz korekta niżej |
| `sposobPowstaniaPodmiotu.podmioty` — podmioty tworzące, z NIP-em | 2 | **krawędź spółka→spółka** |
| `dzial6.polaczeniePodzialPrzeksztalcenie.podmiotyPrzejmowane` | 3 | **`successor_of`** — typ jest w enumie i **nieużywany** |
| `jednostkiTerenoweOddzialy` — oddziały z adresami | 11 | kolejne węzły adresowe |
| `nrDataDecyzjiPrezesaUOKiK` | 1 | wprost łączy z decyzją UOKiK |
| `przedmiotDzialalnosci` | 1 + 138 PKD | branża |
| `wzmiankiOZlozonychDokumentach` — sprawozdania z datami | 26 | historia składania sprawozdań |
| `kapital.*` — kapitał, liczba akcji, wartość akcji, część wpłacona | 4 wartości historyczne | zmiany kapitału w czasie |
| `emisjeAkcji` — serie akcji z uprzywilejowaniem | 6 | struktura właścicielska |
| `daneOWczesniejszejRejestracji` — numer w RHB | 1 | ciągłość sprzed KRS |
| `adresPocztyElektronicznej`, `adresStronyInternetowej` | 3 + 1 | kontakt |

> **Korekta z 2026-09-02.** Pierwsza wersja tego dokumentu twierdziła, że
> nie bierzemy osi czasu. To była nieprecyzyjna lektura kodu: `krs_mapper`
> **ma** `entry_dates()` i `_period()`, i przelicza numery wpisów na daty —
> krawędź adresowa ORLEN-u ma `valid_from = 2001-07-19`. Mechanizm istnieje.
>
> Prawdziwa luka jest węższa i inna: z odpisu 432 KB, mającego 219 wpisów,
> parsery wyciągały **2 encje i 1 krawędź**. Brakowało nie osi czasu, tylko
> parserów kolejnych sekcji. Przekształcenia dopisane — reszta poniżej stoi.

**Historia zmian:** tak, kompletna. **Bulk:** nie ma, jedno zapytanie na podmiot.
**Przyrostowo:** brak wsparcia, porównanie po sumie kontrolnej treści.
**Identyfikator:** KRS + NIP + REGON **w jednym dokumencie** — najlepszy most
identyfikatorowy, jaki mamy.
**Blokada:** masowe pobieranie czeka na opinię prawną (art. 60a).

---

## 2. REGON / BIR GUS — nie mamy wcale

Zero integracji. 5 951 REGON-ów w bazie pochodzi z białej listy VAT, nie z GUS.

**Sprawdzone w dokumentacji `api.stat.gov.pl`:** klucz na wniosek mailem
(`regon_bir@stat.gov.pl`, bezpłatny), limity **10 000/godz., 200/min, 4/s**,
a przekroczenie „nie skutkuje natychmiastową blokadą".

**Co dałoby:** REGON, NIP, KRS, nazwę, adres, formę prawną, PKD — i to dla
podmiotów **bez NIP-u**, których biała lista nie zna. Do entity resolution
to jest kanoniczne źródło.

**Niesprawdzone:** czy BIR1 ma operacje zbiorcze zwracające wiele podmiotów
w jednej odpowiedzi. Jeśli ma, szacunek dwóch tygodni na pełny przebieg spada.

---

## 3. BZP / e-Zamówienia — mamy szczątek

**Bierzemy dziś:** `organizationName`, `organizationNationalId`,
`organizationCity`, `contractorName`, `contractorNationalId`,
`contractorCity`, `cpvCode`, `noticeNumber`, `noticeType`, `publicationDate`,
`orderObject`. Efekt: **124 krawędzie** z 47 dokumentów.

**Czego nie bierzemy** — sprawdzone na żywej odpowiedzi:

`procedureResult`, `submittingOffersDate`, `pdfUrl`, `tenderId`,
`organizationProvince`, `organizationId`, `organizationCountry`, `orderType`,
`clientType`, `isTenderAmountBelowEU`, `bzpTenderPlanNumber`, `outdated`,
`noticeTypeTed` (**łącznik do TED!**), `baseNoticeMOIdentifier`.

**Czego w tym API nie ma w ogóle: wartości zamówienia.** Pole `htmlBody` było
puste w próbce, a kwota jest w treści ogłoszenia. Żeby dostać wartości, trzeba
sięgnąć po `pdfUrl` i parsować — to osobna, znacznie większa robota.

**Poważne ograniczenie, potwierdzone pomiarem:** endpoint wyszukiwania oddaje
**zawsze 10 rekordów**, ignoruje `PageSize`, `PageNumber` i `Page`, a **to samo
okno zapytane dwa razy zwraca inne rekordy**. Zawężenie z godziny do minuty nie
zawęża wyniku. **Archiwum jest tym API nieosiągalne** — nadaje się do
codziennego dociągania nowości, nie do zbudowania historii.

**Identyfikator:** `organizationNationalId` i `contractorNationalId` to NIP-y —
łączą się wprost z resztą bazy.

---

## 4. TED — nie mamy, a działa

**Sprawdzone:** `POST https://api.ted.europa.eu/v3/notices/search` odpowiada
**200 bez klucza**. Zapytanie `buyer-country=POL` zwraca ogłoszenia z polami
`publication-number`, `notice-type`, `buyer-name`, `winner-name`.

**Uwaga o kształcie danych:** pola tekstowe są **wielojęzyczne** — `buyer-name`
to obiekt z kluczami `pol`, `eng`, `deu` i tak dalej. Mapper musi wybierać
język, a nie zakładać napis.

To jest naturalne uzupełnienie BZP: zamówienia powyżej progów unijnych, których
w BZP nie ma, plus `noticeTypeTed` w BZP jako gotowy łącznik.

**Niesprawdzone:** czy jest pobieranie zbiorcze i czy da się filtrować
przyrostowo po dacie publikacji. Sprawdziłem wyłącznie, że wyszukiwanie działa.

---

## 5. Fundusze Europejskie / dane.gov.pl — nie mamy, API działa

**Sprawdzone:** `api.dane.gov.pl/1.4/datasets?q=...` odpowiada 200 i zwraca
m.in. **„Lista beneficjentów Funduszy Europejskich 2007-2013"** oraz
**„Wykaz beneficjentów Wspólnej Polityki Rolnej"**.

**Niesprawdzone:** struktura tych zbiorów — czy niosą NIP beneficjenta
(bez niego połączenie z resztą bazy jest zgadywaniem po nazwie), kwoty
dofinansowania, nazwę programu i daty. Trzeba pobrać zasób i obejrzeć.

Wyszukiwarka pełnotekstowa dane.gov.pl jest słaba — zapytania o „spółki Skarbu
Państwa" i „oświadczenia majątkowe" zwróciły wyniki niezwiązane z tematem.

---

## 6. CRBR — nie mamy, kształt żądania nieustalony

`POST https://crbr.podatki.gov.pl/adcrbr/api/wyszukajSpolke` istnieje i odpowiada
**ustrukturyzowanym błędem**, więc jest publiczny i przyjmuje NIP. Każdy wariant
ciała, jaki wysłałem, dostawał `1022 Niepoprawny NIP` przy NIP-ie o poprawnej
sumie kontrolnej. Do ustalenia podglądem ruchu w przeglądarce.

W bundlu aplikacji **nie ma eksportu zbiorczego** — są wyłącznie eksporty wyniku
pojedynczego wyszukiwania. To akurat dobrze: model „zapytanie przy oglądaniu
podmiotu" jest tu jedynym, który obronimy.

Daje to, czego w KRS nie ma w ogóle: **kto faktycznie kontroluje spółkę**,
z imieniem, nazwiskiem i PESEL-em.

---

## 7. BIP-y instytucji publicznych — **nie da się potwierdzić**

BIP to nie jest jeden system. To **tysiące osobnych stron** o wspólnym
minimalnym standardzie prawnym i zupełnie różnej technicznej postaci. Nie
znalazłem centralnego API ani agregatora i **nie potwierdzam, że istnieje**.

Realna droga to scrapowanie per instytucja — czyli tyle integracji, ile
instytucji. To nie jest rozszerzenie istniejącego źródła, tylko osobny projekt.

---

## 8. Rejestry umów instytucji publicznych — **nie da się potwierdzić**

Centralny rejestr umów miał powstać przy Ministerstwie Finansów.
`rejestrumow.podatki.gov.pl` **nie rozwiązuje się z tej sieci** (kod 000),
a wyszukiwanie na dane.gov.pl nie znalazło odpowiadającego zbioru.

**Nie twierdzę, że nie istnieje** — twierdzę, że nie potwierdziłem. Zanim
cokolwiek planować, trzeba ustalić, czy działa i pod jakim adresem.

Gdyby działał, byłby bardzo wartościowy: kontrahent + przedmiot + kwota + data
to gotowa krawędź instytucja→firma z wartością, czego BZP nie daje.

---

## 9. Oświadczenia majątkowe — **nie da się potwierdzić**

Nie znalazłem centralnego zbioru. Publikowane są w BIP-ach, przeważnie jako
**skany PDF**, często bez warstwy tekstowej. Dane osobowe są tam częściowo
zaczernione, a zakres publikacji zależy od funkcji.

Wartość byłaby duża — udziały i funkcje w spółkach deklarowane wprost — ale
droga prowadzi przez punkt 7, plus OCR, plus poważna analiza prawna.

---

## 10. Spółki Skarbu Państwa i JST — **nie da się potwierdzić**

Wyszukiwanie na dane.gov.pl nie zwróciło wykazu spółek z udziałem Skarbu
Państwa ani samorządów. Pojawił się natomiast **„Wykaz przedsiębiorstw
państwowych"** — to co innego (przedsiębiorstwo państwowe to nie spółka).

Częściowo da się to wyprowadzić **z danych, które już mamy**: udziałowcem
w KRS bywa Skarb Państwa albo gmina wskazana z nazwy. To nie zastępuje wykazu,
ale jest dostępne bez nowego źródła.

---

## Tabela zbiorcza

| SOURCE | CURRENT IMPLEMENTATION | MISSING DATA | VALUE | DIFFICULTY | RECOMMENDED ACTION | PRIO |
|---|---|---|---|---|---|---|
| **KRS — historia wpisów** | stan bieżący | `naglowekP.wpis` (219) + `nrWpisuWprow/Wykr` przy każdym polu | bardzo duża — `valid_from`/`valid_to` dla każdego faktu | mała: dane w dokumentach, które już mamy | rozszerzyć mapper o oś czasu wpisów | **P0** |
| **KRS — przekształcenia** | brak | `dzial6`, `sposobPowstaniaPodmiotu.podmioty` (z NIP) | duża — krawędź spółka→spółka, typ `successor_of` już jest w enumie | mała | dodać do mappera | **P0** |
| **KRS — oddziały, PKD, kapitał, sprawozdania** | brak | 11 oddziałów, 139 PKD, 4 wartości kapitału, 26 wzmianek | średnia | mała | dodać do mappera | **P1** |
| **BZP — pełny zestaw pól** | 11 pól | `procedureResult`, `submittingOffersDate`, `pdfUrl`, `noticeTypeTed`, `tenderId`, `orderType` | średnia; `noticeTypeTed` łączy z TED | mała | rozszerzyć mapper | **P0** |
| **BZP — wartości zamówień** | brak | kwoty (nie ma ich w API, są w PDF) | duża | **wysoka** — parsowanie PDF | odłożyć | **P2** |
| **BZP — archiwum** | 47 dokumentów | reszta archiwum | duża | **niewykonalne tym API** — niedeterministyczne, 10 rekordów, brak paginacji | szukać innej drogi albo odpuścić | **P2** |
| **REGON / BIR1** | brak | REGON, NIP, KRS, PKD, forma prawna, podmioty bez NIP | duża — kanoniczne źródło do entity resolution | średnia; **wymaga wniosku o klucz** | wystąpić o klucz, potem zaimplementować | **P1** |
| **TED** | brak | ogłoszenia unijne: zamawiający, wykonawca, wartości | duża — uzupełnia BZP powyżej progów | średnia; pola wielojęzyczne | zbadać bulk, potem klient | **P1** |
| **Fundusze UE / dane.gov.pl** | brak | beneficjenci, kwoty, programy | duża — krawędź firma→finansowanie publiczne | **nieznana** do czasu obejrzenia zbiorów | pobrać zasób, sprawdzić czy jest NIP | **P1** |
| **CRBR** | brak | beneficjenci rzeczywiści z nazwiskami | bardzo duża — jedyne źródło rzeczywistej kontroli | mała, gdy ustalimy kształt żądania | ustalić żądanie, model na żądanie | **P1** |
| **Rejestry umów** | brak | kontrahent, kwota, data | duża | **nieznana** — nie potwierdzono istnienia | ustalić, czy działa | **P2** |
| **Spółki SP / JST** | brak | udziały państwa i samorządów | średnia | **nieznana** — nie znaleziono wykazu | częściowo wyprowadzić z KRS | **P2** |
| **BIP-y** | brak | umowy, uchwały, konkursy | duża, ale rozproszona | **bardzo wysoka** — tysiące osobnych stron | osobny projekt, nie rozszerzenie | **P2** |
| **Oświadczenia majątkowe** | brak | udziały i funkcje osób publicznych | bardzo duża | **bardzo wysoka** — PDF-y w BIP-ach, OCR, analiza prawna | po BIP-ach | **P2** |

---

## Pięć zmian, które zrobiłbym następnie

**1. Oś czasu z KRS (P0).** Wczytać `naglowekP.wpis` i mapować
`nrWpisuWprow`/`nrWpisuWykr` na `valid_from`/`valid_to` każdej krawędzi
i atrybutu. To wypełnia bitemporalność, którą model ma od początku i której
nie karmimy. Dane są w dokumentach, które już pobieramy — zero nowych zapytań.

**2. Przekształcenia i podmioty tworzące z KRS (P0).** `dzial6` i
`sposobPowstaniaPodmiotu.podmioty` dają krawędzie spółka→spółka z NIP-em po
obu stronach. Typ `successor_of` jest w enumie i nie ma **ani jednej** krawędzi.
Też bez nowych zapytań.

**3. Pełny mapper BZP (P0).** Jedenaście pól z trzydziestu czterech to strata
przy źródle, które już odpytujemy. `noticeTypeTed` daje przy okazji gotowy
łącznik do TED.

**4. Wniosek o klucz REGON/BIR1 (P1).** Jedno działanie po Twojej stronie —
mail na `regon_bir@stat.gov.pl` — odblokowuje kanoniczne źródło identyfikatorów
z limitem 10 000 zapytań na godzinę. To najlepszy stosunek wartości do wysiłku
w całym zestawieniu, ale wymaga człowieka.

**5. Rozpoznanie funduszy UE (P1).** Pobrać „Listę beneficjentów Funduszy
Europejskich" i sprawdzić **jedną rzecz: czy jest tam NIP**. Bez niego
połączenie z bazą będzie dopasowaniem po nazwie, czyli tym, czego niezmiennik
N4 zabrania. Godzina pracy rozstrzyga, czy to źródło ma dla nas sens.

Pierwsze trzy nie wymagają ani jednego nowego zapytania do żadnego rejestru —
to jest przetworzenie dokumentów, które już leżą w `raw_documents`.
