# Plan pobierania z nowych źródeł

Kolejność i uzasadnienie dla źródeł, których jeszcze nie mamy. Wszystko
sprawdzone zapytaniem — czego nie sprawdziłem, jest napisane wprost.

Stan wyjściowy: [02-zrodla-danych.md](02-zrodla-danych.md). Odporność pobierania
i szacunki kosztu: [07-pobieranie-danych.md](07-pobieranie-danych.md).

---

## Liczba, która układa ten plan

| rodzaj krawędzi | ile | udział |
|---|---:|---:|
| `sole_proprietor_of` — własna działalność, 1:1 | 3 552 839 | 54,9% |
| `registered_at` — adres | 2 892 400 | 44,7% |
| `parent_of` — spółka–spółka (GLEIF) | 21 306 | 0,3% |
| `contractor_of` — zamówienia (BZP) | 124 | 0,0% |

**16 182 podmioty z 3,6 mln** mają jakiekolwiek powiązanie, które nie jest
„moja własna działalność" albo „mój adres". To jest **0,45%**.

Projekt odpowiada na pytanie „jak ta firma jest powiązana z innymi firmami
i osobami". Dla 99,5% bazy odpowiedź brzmi dziś: **przez adres, albo wcale.**

Dlatego plan nie jest uszeregowany po koszcie, tylko po tym, **czy źródło
dokłada krawędzie odpowiadające na to pytanie**. To rozróżnienie zmienia
kolejność, bo dwa najtańsze źródła nie dokładają ich wcale.

---

## Podział: co buduje graf, a co jest hydrauliką

### Buduje graf

| źródło | jakie krawędzie | blokada |
|---|---|---|
| **BZP — pełne archiwum** | zamawiający ↔ wykonawca, oba z NIP-em | **brak** |
| **Spółki cywilne z CEIDG** | osoba ↔ osoba | **brak** |
| **KRS masowo** | organ → spółka (nazwiska zamaskowane), wspólnik → spółka | opinia prawna, art. 60a |
| **CRBR** | beneficjent rzeczywisty → spółka | model na żądanie |
| **MSiG** | osoba → spółka, **z nazwiskami** | opinia prawna |

### Hydraulika — zero krawędzi

| źródło | co daje | po co |
|---|---|---|
| **Biała lista VAT** | NIP ↔ KRS ↔ REGON, rachunki | bez tego nie wiadomo, o które spółki pytać KRS |
| **REGON / BIR1** | podmioty bez NIP-u, PKD | pokrycie i klasyfikacja branżowa |
| **KRZ** | upadłości, zakazy | sygnał ryzyka, atrybut nie krawędź |

To rozróżnienie nie deprecjonuje hydrauliki: most identyfikatorowy jest
warunkiem wejścia do KRS-u. Ale trzeba je nazwać, bo „zrobiliśmy białą listę
i REGON" brzmi jak postęp w budowie grafu, a nim nie jest.

---

## Co robić teraz, bez żadnej decyzji

Dwie rzeczy są odblokowane i obie dokładają krawędzie.

**BZP — pełne archiwum.** To jedyne niezablokowane źródło, które buduje graf na
skalę. Mamy 47 ogłoszeń i 124 krawędzie; archiwum idzie wstecz o lata. API jest
publiczne, bez klucza, naturalnie przyrostowe (schodzimy po dacie publikacji do
tej, którą już mamy), a pole `contractors` niesie wykonawców z NIP-em.
Ograniczenie: **API oddaje 10 rekordów na stronę** niezależnie od `PageSize`,
więc rok danych to rzędu kilkudziesięciu tysięcy zapytań — kilka godzin przy
dwóch na sekundę. Klient i mapper już istnieją; brakuje przebiegu wstecz.

**Spółki cywilne z CEIDG.** 3 328 wpisów, dane już w `raw_documents`, zero
ruchu sieciowego, zero nowego ryzyka. Jedyne dziś dostępne powiązanie
osoba–osoba.

---

## Co wymaga jednej Twojej decyzji

**Klucz do REGON/BIR1** — wniosek mailem na `regon_bir@stat.gov.pl`. Tego nie
zrobię za Ciebie. Limity są hojne: **10 000 zapytań na godzinę, 200 na minutę,
4 na sekundę**, a ich przekroczenie „nie skutkuje natychmiastową blokadą".
To jest zupełnie inna liga niż dzienna kwota MF.

**Opinia prawna** — obejmuje naraz KRS masowo (art. 60a) i MSiG. Jedno pytanie
do prawnika odblokowuje dwa najgrubsze źródła krawędzi osobowych. Dopóki go
nie ma, oba stoją i nie ma sensu ich planować w szczegółach.

---

## Korekta z 2026-09-01, po pierwszym przebiegu

Dwie rzeczy, których nie wiedziałem, pisząc ten plan.

**MF ma dzienny limit zapytań na adres IP.** Kod `WL-191`, komunikat „Limit
żądań dla tego adresu IP został na dziś wyczerpany". Nie znalazłem go
udokumentowanego; wyczerpał się po około 5 600 numerach. Przy takim pułapie
118 676 zapytań to nie jest zadanie na kilkanaście godzin, tylko na lata.

**Ale liczba 118 676 była i tak błędna.** Z 3 560 269 NIP-ów w bazie
**3 552 839 należy do jednoosobowych działalności z CEIDG, które numeru KRS nie
mają z definicji.** Odpytywanie ich o most identyfikatorowy to praca bez
możliwego wyniku: z 5 610 wydanych numerów KRS przybyło dla **105**, czyli 1,9
procent.

Zbiór, który faktycznie może nieść most, to **7 343 numery** — podmioty z NIP-em,
bez KRS-u, niebędące jednoosobową działalnością. To jest **245 zapytań**,
mieszczące się w dziennym limicie z ogromnym zapasem.

Czyli: limit nie zablokował białej listy. Zablokował ją **ten plan**, który
wycelował ją w trzy i pół miliona podmiotów, dla których nie miała nic do
powiedzenia. Poprawione — `enrich-whitelist` domyślnie chodzi po zbiorze
`bridge`.

Do czego dzienny limit **nadal** ma znaczenie: REGON przybywa także dla
działalności jednoosobowych (55 procent trafień). Jeżeli chcemy REGON dla całej
bazy, to jest osobny cel i wtedy potrzebny jest plik zbiorczy MF albo rozłożenie
przebiegu na wiele dni. **Adresu pliku zbiorczego nie potwierdziłem.**

---

## Biała lista VAT — hydraulika, ale warunek wejścia do KRS-u

To źródło było na liście jako „status VAT i rachunki bankowe". Sprawdzenie
pokazało coś ważniejszego: **odpowiedź zawiera `nip`, `regon` i `krs` naraz**.

```
GET https://wl-api.mf.gov.pl/api/search/nips/{do 30 NIP-ów}?date=RRRR-MM-DD
```

Zmierzone:

* partia to **maksymalnie 30 NIP-ów** — 31 daje `WL-130 Przekroczono maksymalną
  liczbę argumentów zapytania`;
* obowiązuje **dzienny limit zapytań na adres IP** (`WL-191`) — patrz korekta
  wyżej;
* odpowiedź na podmiot: `name, nip, regon, krs, statusVat, workingAddress,
  residenceAddress, accountNumbers, registrationLegalDate, removalBasis,
  representatives, authorizedClerks, partners`;
* dla PKN ORLEN wróciło 236 numerów rachunków.

**Dlaczego to jest pierwsze.** Dziś mamy 23 788 numerów KRS i niemal wszystkie
pochodzą z GLEIF, czyli z próbki przechylonej w stronę dużych podmiotów — nie
wiemy nawet, o które spółki zapytać KRS. Biała lista daje ten spis z NIP-ów,
które już mamy, i kosztuje **245 zapytań**, bo tylko tyle podmiotów w bazie może
mieć numer KRS.

To jest tańsza droga do tego samego, co REGON/BIR1, i nie wymaga wniosku
o klucz. **REGON zostaje w planie**, ale schodzi za białą listę: jego przewagą
jest pokrycie podmiotów bez NIP-u i PKD, a nie spis identyfikatorów.

Poza tym: wspólny numer rachunku bankowego to twardy sygnał powiązania między
podmiotami, którego nie da się dostać z żadnego rejestru sądowego.

**Czego to źródło nie da.** Pola `representatives`, `authorizedClerks`
i `partners` **istnieją w schemacie, ale u czynnych podatników są puste** —
sprawdzone na trzech spółkach z o.o., wszędzie zero. Nie jest to więc droga do
warstwy osobowej i nie należy jej tak planować. Nie sprawdziłem, czy pola
wypełniają się dla podmiotów wykreślonych z rejestru VAT albo takich, którym
odmówiono rejestracji — schemat sugeruje właśnie taki przypadek użycia i to
jest tania rzecz do sprawdzenia przy okazji importu.

**Przyrostowość.** `date` jest parametrem obowiązkowym, więc stan da się
odpytać na dowolny dzień. Do odświeżania wystarczy przebieg po podmiotach,
których `statusVat` albo rachunki mogły się zmienić — pełny przebieg nie jest
potrzebny częściej niż raz na kwartał.

**Uwaga na dane osobowe.** Odpowiedź zawiera pole `pesel` (dla osób fizycznych
prowadzących działalność). Obowiązuje reguła bez wyjątku: haszowanie przed
zapisem, także do `raw_documents`.

---

## Spółki cywilne z CEIDG — pierwsze powiązanie osoba–osoba

3 328 wpisów oznaczonych jako „działalność prowadzona wyłącznie w formie spółki
cywilnej". Dane już pobrane, pole dziś nieczytane.

Zero nowego ryzyka prawnego i zero nowego ruchu sieciowego: to jest przetworzenie
dokumentów, które leżą w `raw_documents`. Jedyne miejsce w całej bazie, gdzie
z legalnie posiadanych danych da się dziś zbudować krawędź między dwiema
osobami.

Skala jest mała i to jest uczciwa część opisu — 3 328 wpisów przy 3,55 mln osób
nie zmienia charakteru bazy. Zmienia to, że warstwa osobowa przestaje być
wyłącznie relabelingiem.

---

## KRS masowo — wartościowy mimo maskowania

Nazwiska są zamaskowane i to jest przesądzone ([02](02-zrodla-danych.md)).
Ale odpis daje bez nazwisk: formę prawną, kapitał zakładowy, PKD, adres,
skład organów **co do liczby i funkcji**, daty powołania i odwołania, historię
nazw oraz **KRS i NIP w jednym dokumencie**.

**Hipoteza warta jednego eksperymentu przed całym importem.** Jeżeli maskowanie
jest deterministyczne, to ta sama osoba w dwóch spółkach daje ten sam wzorzec
(`F*****`, PESEL `5**********`). Wtedy da się zbudować krawędź „ten sam ktoś
siedzi w obu spółkach" **bez wiedzy, kto to jest** — a to jest dokładnie
pytanie, na które ma odpowiadać ten projekt.

Eksperyment: wziąć dwie spółki o znanym wspólnym członku zarządu i porównać
zamaskowane pola. Koszt: dwa zapytania. Jeżeli wzorzec jest stabilny, zmienia
to priorytet całego KRS-u; jeżeli maskowanie jest losowane per dokument,
odpada i trzeba to zapisać, żeby nikt nie wracał do pomysłu.

**Uwaga na niezmiennik N4.** Zbieżność zamaskowanego wzorca to **jeden** sygnał,
i to słaby: `K***` pasuje do dziesiątek tysięcy osób. Sam wzorzec nazwiska nie
może scalać osób. Dopiero zamaskowany PESEL — 11 znaków, z których widać
pierwszy — plus zgodność imienia i nazwiska to trzy niezależne cechy, i to jest
minimum do rozmowy. Nawet wtedy wynik idzie do kolejki przeglądu, nie do
automatycznego scalenia.

**Blokada.** Masowe pobieranie KRS czeka na opinię prawnika co do art. 60a
ustawy o KRS. Stan bez zmian.

---

## CRBR — na żądanie, nie kopia rejestru

API jest publiczne: `POST https://crbr.podatki.gov.pl/adcrbr/api/wyszukajSpolke`,
odpowiada ustrukturyzowanym błędem, więc istnieje i przyjmuje NIP. **Nie udało
mi się trafić w oczekiwany kształt żądania** — każdy wariant, jaki próbowałem,
dostawał `1022 Niepoprawny NIP` przy NIP-ie o poprawnej sumie kontrolnej.
Do ustalenia podglądem ruchu w przeglądarce; to jest kwadrans pracy, nie
niewiadoma.

W bundlu aplikacji nie ma eksportu zbiorczego — są wyłącznie eksporty wyniku
pojedynczego wyszukiwania (`eksportWyszukSpolkiXml`,
`eksportWynikiWyszBeneficjentaXml`). **I dobrze**: model „pojedyncze zapytanie
przy oglądaniu podmiotu", taki jak dziś przy KRS, jest tu jedynym, który
obronimy. Budowanie kopii rejestru beneficjentów rzeczywistych to inna rozmowa
i inne ryzyko.

CRBR daje to, czego w KRS nie ma w ogóle: kto faktycznie kontroluje spółkę,
a nie kto jest wpisany do zarządu.

---

## KRZ — atrybut ryzyka, nie krawędź

`krz.ms.gov.pl` odpowiada przekierowaniem, portal jest publiczny i bez
logowania. **Nie zbadałem jego API.** Nie potrafię dziś podać ani wolumenu, ani formatu, ani
przyrostowości, więc nie ma tu planu — jest zadanie rozpoznawcze.

Wartość jest oczywista i inna niż reszty: upadłości, restrukturyzacje i zakazy
prowadzenia działalności to sygnał ryzyka o osobie, a nie kolejna krawędź
w grafie.

---

## MSiG — ostatni, bo najpierw prawnik

Technicznie gotowe do wzięcia: każdy numer od 1996 jako PDF, około 250 numerów
rocznie po 0,5–2 MB, w numerze 1/2026 zero maskowania i 36 jawnych PESEL-i.
Pełny opis i warunki: [02-zrodla-danych.md](02-zrodla-danych.md).

Kolejność jest tu celowa. MSiG jest jedyną znaną drogą do masowej warstwy
`osoba → spółka`, więc pokusa, żeby wziąć go najpierw, jest największa — i to
jest dokładnie powód, żeby zrobić go ostatni. Pięć punktów wyżej daje wartość
bez otwierania pytania, na które nie mamy odpowiedzi.

---

## REGON / BIR1 — limity, które warto znać

Sprawdzone w dokumentacji `api.stat.gov.pl` 2026-09-01:

* klucz użytkownika **na wniosek mailem** na `regon_bir@stat.gov.pl`, bezpłatny;
* **10 000 zapytań na godzinę, 200 na minutę, 4 na sekundę**;
* przekroczenie limitów „nie skutkuje natychmiastową blokadą dostępu" —
  usługobiorca zostaje poinformowany.

Przy 10 tys. na godzinę pełny przebieg po 3,5 mln podmiotów to około dwóch
tygodni ciągłej pracy. Do rozważenia razem z pytaniem, czy REGON jest nam
potrzebny dla **całej** bazy, czy tylko tam, gdzie brakuje identyfikatorów.

Nie sprawdziłem, czy BIR1 ma operacje zbiorcze zwracające wiele podmiotów
w jednej odpowiedzi — jeżeli ma, powyższy szacunek spada odpowiednio.

---

## Co z tego wynika dla warstwy pobierania

Żadne z tych źródeł nie wymaga nowej klasy klienta. Każde to wpis w `PROFILES`
plus mapper:

| źródło | tempo | partia | przyrostowo |
|---|---|---|---|
| biała lista VAT | do ustalenia, brak udokumentowanego limitu | 30 NIP-ów | po dacie stanu |
| KRS | ~1 zapytanie/s | 1 podmiot | brak — hash treści |
| CRBR | na żądanie | 1 podmiot | nie dotyczy |
| MSiG | ~1 plik/s | 1 numer | numery przyrastają, stare się nie zmieniają |

Dwie rzeczy do zrobienia w samej warstwie, zanim ruszy pierwszy z tych importów:

1. **Limit tempa białej listy jest nieznany.** Nie znalazłem udokumentowanego
   progu. Profil ma startować konserwatywnie i podnosić się dopiero po
   przebiegu bez `429`, a nie odwrotnie.
2. **Haszowanie PESEL-a musi działać na etapie parsowania**, przed zapisem do
   `raw_documents`. Dziś reguła jest zapisana w CLAUDE.md, ale żadne źródło
   jeszcze jej nie potrzebowało — biała lista będzie pierwszym, które ma pole
   `pesel`, więc mechanizm trzeba mieć **przed** tym importem, nie po nim.
