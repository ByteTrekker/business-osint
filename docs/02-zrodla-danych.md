# Źródła danych

Zasada: **wyłącznie źródła oficjalne lub otwarte.** Żadnego scrapowania
komercyjnych agregatorów — to ryzyko prawne i uzależnienie produktu od cudzej
infrastruktury.

## Priorytet wdrożenia

| # | źródło | co daje | forma | trudność |
|---|---|---|---|---|
| 1 | **KRS** (api-krs.ms.gov.pl) | spółki, zarządy, wspólnicy, adresy, historia | REST JSON | średnia |
| 2 | **REGON / GUS (BIR1)** | pełna lista podmiotów, PKD, adresy | SOAP + paczki CSV | średnia |
| 3 | **CRBR** | beneficjenci rzeczywiści | REST/XML | średnia |
| 4 | **CEIDG** | jednoosobowe działalności | REST (wymaga klucza) | niska |
| 5 | **Biała lista VAT (MF)** | rachunki, status VAT | REST | niska |
| 6 | **BZP / TED** | zamówienia publiczne | REST / OCDS | wysoka |
| 7 | **Dotacje UE (SL2014/CST)** | beneficjenci dotacji | CSV / API | wysoka |
| 8 | **eKRS — sprawozdania finansowe** | dane finansowe | XML/PDF | bardzo wysoka |

## KRS — szczegóły operacyjne

```
GET https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json
GET https://api-krs.ms.gov.pl/api/krs/OdpisPelny/{krs}?rejestr=P&format=json
```

* `rejestr=P` — przedsiębiorcy, `rejestr=S` — stowarzyszenia i fundacje.
* **Odpis pełny zawiera wpisy wykreślone** — bez niego nie ma historii powiązań.
  Do pierwszego importu bierzemy pełny, do codziennego odświeżania aktualny.
* Brak oficjalnego rate limitu i brak SLA. Trzymamy się ~1 req/s — przy 700 tys.
  podmiotów to ~8 dni ciągłego pobierania. **To jest ograniczenie harmonogramu
  projektu, nie techniczne.**
* Brak bulk exportu. Listę numerów KRS bierzemy z paczek REGON.
* Odpowiedzi zapisujemy do `raw_documents` **przed** parsowaniem — zawsze.

## REGON / GUS

API BIR1 wymaga klucza (bezpłatny, wniosek). Wolne przy zapytaniach
pojedynczych, ale GUS publikuje też **paczki zbiorcze** — i to jest właściwa
droga do pierwszego załadowania listy podmiotów. To jest miejsce, w którym
Polars zarabia na siebie.

## CRBR

Rejestr beneficjentów rzeczywistych. Dane, których **nie ma w KRS**, a są
kluczowe dla compliance i AML — to jest realna wartość dodana, nie kolejna
kopia KRS-u. Dostęp po numerze NIP.

## Zasady wspólne dla wszystkich źródeł

1. **Surowy dokument zawsze przed parsowaniem** (`raw_documents` + sha256).
2. **Dedup po treści** — niezmieniony dokument nie tworzy nowego snapshotu.
3. **Rate limit i backoff** — zablokowany adres IP zatrzymuje cały projekt.
4. **Mapper to czysta funkcja z testami na zamrożonym fixture** — zmiana schematu
   po stronie urzędu ma dawać czerwony test, nie cichy zanik danych w grafie.
5. **Każde źródło ma wpis w tabeli `sources`** z licencją i częstotliwością
   odświeżania.
6. **`User-Agent` z kontaktem** — jeżeli obciążacie cudze API, dajcie się namierzyć.

## Licencje

Dane z rejestrów publicznych są co do zasady dostępne do ponownego wykorzystania
(ustawa o otwartych danych), ale **warunki różnią się między rejestrami** —
niektóre wymagają wskazania źródła i daty pobrania. Dlatego `sources.license`
jest osobną kolumną, a interfejs pokazuje źródło przy każdej relacji. To nie jest
tylko zgodność z prawem: to jest funkcja produktu.
