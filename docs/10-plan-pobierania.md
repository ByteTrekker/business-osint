# Plan pobierania z nowych źródeł

Kolejność i uzasadnienie dla źródeł, których jeszcze nie mamy. Wszystko poniżej
sprawdzone zapytaniem 2026-09-01 — jeżeli czegoś nie sprawdziłem, jest to
napisane wprost.

Stan wyjściowy: [02-zrodla-danych.md](02-zrodla-danych.md). Odporność pobierania
i szacunki kosztu: [07-pobieranie-danych.md](07-pobieranie-danych.md).

---

## Kolejność

| # | źródło | co odblokowuje | blokada |
|---|---|---|---|
| 1 | **biała lista VAT** | mapowanie NIP ↔ KRS ↔ REGON dla całej bazy | brak |
| 2 | **spółki cywilne z CEIDG** | pierwsze powiązania osoba–osoba | brak |
| 3 | **KRS masowo** | zarządy, wspólnicy, historia (nazwiska zamaskowane) | opinia prawna do art. 60a |
| 4 | **CRBR** | beneficjenci rzeczywiści z nazwiskami | model „na żądanie", nie kopia rejestru |
| 5 | **KRZ** | upadłości, zakazy prowadzenia działalności | brak API — do zbadania |
| 6 | **MSiG** | nazwiska bez maskowania, masowo | opinia prawna, patrz 02 |

Punkty 1 i 2 nie mają blokad i nie wymagają nowych decyzji. Reszta wymaga.

---

## 1. Biała lista VAT — najpierw, bo jest kręgosłupem

To źródło było na liście jako „status VAT i rachunki bankowe". Sprawdzenie
pokazało coś ważniejszego: **odpowiedź zawiera `nip`, `regon` i `krs` naraz**.

```
GET https://wl-api.mf.gov.pl/api/search/nips/{do 30 NIP-ów}?date=RRRR-MM-DD
```

Zmierzone:

* partia to **maksymalnie 30 NIP-ów** — 31 daje `WL-130 Przekroczono maksymalną
  liczbę argumentów zapytania`;
* odpowiedź na podmiot: `name, nip, regon, krs, statusVat, workingAddress,
  residenceAddress, accountNumbers, registrationLegalDate, removalBasis,
  representatives, authorizedClerks, partners`;
* dla PKN ORLEN wróciło 236 numerów rachunków.

**Dlaczego to jest pierwsze.** Dziś mamy 23 683 numery KRS i wszystkie pochodzą
z GLEIF, czyli z próbki przechylonej w stronę dużych podmiotów — nie wiemy
nawet, o które spółki zapytać KRS. Biała lista daje ten spis z NIP-ów, które
już mamy: 3 560 269 NIP-ów podzielone po 30 to **118 676 zapytań**. Przy jednym
zapytaniu na sekundę to około półtorej doby, przy pięciu — siedem godzin.

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

## 2. Spółki cywilne z CEIDG — pierwsze powiązanie osoba–osoba

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

## 3. KRS masowo — wartościowy mimo maskowania

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

## 4. CRBR — na żądanie, nie kopia rejestru

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

## 5. KRZ — do zbadania, nie do zaplanowania

`krz.ms.gov.pl` odpowiada, portal jest publiczny i bez logowania. **Nie zbadałem
jego API.** Nie potrafię dziś podać ani wolumenu, ani formatu, ani
przyrostowości, więc nie ma tu planu — jest zadanie rozpoznawcze.

Wartość jest oczywista i inna niż reszty: upadłości, restrukturyzacje i zakazy
prowadzenia działalności to sygnał ryzyka o osobie, a nie kolejna krawędź
w grafie.

---

## 6. MSiG — ostatni, bo najpierw prawnik

Technicznie gotowe do wzięcia: każdy numer od 1996 jako PDF, około 250 numerów
rocznie po 0,5–2 MB, w numerze 1/2026 zero maskowania i 36 jawnych PESEL-i.
Pełny opis i warunki: [02-zrodla-danych.md](02-zrodla-danych.md).

Kolejność jest tu celowa. MSiG jest jedyną znaną drogą do masowej warstwy
`osoba → spółka`, więc pokusa, żeby wziąć go najpierw, jest największa — i to
jest dokładnie powód, żeby zrobić go ostatni. Pięć punktów wyżej daje wartość
bez otwierania pytania, na które nie mamy odpowiedzi.

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
