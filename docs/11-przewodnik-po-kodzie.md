# Przewodnik po kodzie

Dokument dla kogoś, kto zna programowanie, ale niekoniecznie Pythona i nie zna
tej aplikacji. Nie opisuje każdej linii — opisuje **co robi każda część i
dlaczego akurat tak**. Przy okazji tłumaczy konstrukcje Pythona, które w tym
kodzie występują często i mogą być niejasne.

Stan na dzień pisania: 11 068 linii Pythona, około 9,57 mln encji
i 6,47 mln krawędzi w grafie.

---

## 1. Co ta aplikacja właściwie robi

Odpowiada na pytanie **„jak ta firma jest powiązana z innymi firmami
i osobami"**. Nie „co jest o niej wpisane w rejestrze" — to potrafi każda
wyszukiwarka KRS. Różnica jest w tym, że my budujemy **graf**: wierzchołkami
są firmy, osoby i adresy, a krawędziami relacje między nimi.

Dane pochodzą z publicznych rejestrów (CEIDG, KRS, GLEIF, BZP, PRG). Ściąga je
warstwa ETL, zapisuje do PostgreSQL, a API wystawia je jako JSON, który
konsumuje frontend w Next.js.

```
rejestry  →  ETL  →  PostgreSQL  →  API (FastAPI)  →  frontend (Next.js)
             ↑                        ↑
        etl/fetching              repositories/
    (retry, limity tempa)      (surowy SQL do odczytu)
```

---

## 2. Jak czytać strukturę katalogów

```
backend/src/business_osint/
  domain/        czysta logika — ZERO dostępu do bazy i sieci
  db/            modele SQLAlchemy: opis tabel w Pythonie
  repositories/  zapytania odczytowe (surowy SQL)
  api/v1/        warstwa HTTP: walidacja wejścia + mapowanie na JSON
  schemas/       kontrakty pydantic — kształt odpowiedzi API
  etl/           pobieranie i ładowanie danych
  etl/sources/   po jednym module na rejestr: „jak rozmawiać z tym API"
  etl/fetching/  wspólna odporność: ponawianie, limity tempa, bezpiecznik
```

**Reguła, którą warto zapamiętać:** funkcja trafia do warstwy zgodnej ze swoimi
zależnościami. Jeżeli czegoś potrzebuje z bazy — nie należy do `domain/`.

Po co ten podział? `domain/` da się testować bez uruchamiania Postgresa,
w milisekundach. Cały zestaw testów jednostkowych chodzi ~0,2 s, więc można go
puszczać po każdej zmianie. Gdyby logika była wymieszana z zapytaniami, każdy
test wymagałby bazy i nikt by ich nie uruchamiał.

---

## 3. Warstwa `domain/` — reguły bez świata zewnętrznego

To najmniejsza i najważniejsza część. Osiem plików, same czyste funkcje.

### `normalization.py` — sprowadzanie napisów do porównywalnej postaci

Największy plik w tej warstwie (446 linii) i najczęściej używany. Rejestry
zapisują tę samą rzecz na wiele sposobów: „ORLEN S.A.", „Orlen Spółka
Akcyjna", „ORLEN SA". Żeby je porównać, trzeba je najpierw sprowadzić do
wspólnej postaci.

```python
def normalize_company_name(name: str) -> str:
    ...
```

Funkcje tutaj mają wspólną cechę: **dla tego samego wejścia zawsze zwracają to
samo i nie dotykają niczego na zewnątrz**. Dzięki temu da się je testować
bez żadnej infrastruktury, a testy mutacyjne (patrz §10) mogą sprawdzić, czy
testy naprawdę pilnują reguły.

Przykład z tego pliku, pokazujący pewną pułapkę:

```python
def zahaszuj_pesele(dane: Any, pepper: str) -> Any:
    """Zwraca kopię dokumentu z każdym polem `pesel` zamienionym na skrót."""
    if isinstance(dane, dict):
        wynik: dict[str, Any] = {}
        for klucz, wartosc in dane.items():
            if klucz.lower() == "pesel" and wartosc is not None:
                ...
            else:
                wynik[klucz] = zahaszuj_pesele(wartosc, pepper)   # rekurencja
        return wynik
    if isinstance(dane, list):
        return [zahaszuj_pesele(element, pepper) for element in dane]
    return dane
```

**Co tu jest pythonowego:**

* `isinstance(x, dict)` — sprawdzenie typu w czasie działania. Python nie ma
  przeciążania funkcji po typie, więc rozgałęzienie robi się ręcznie.
* `[f(x) for x in lista]` — *list comprehension*, zwięzły odpowiednik pętli
  budującej listę. Czyta się jak „dla każdego elementu zrób f".
* Funkcja wywołuje samą siebie — dokument JSON jest drzewem o nieznanej
  głębokości, więc rekurencja jest tu naturalna.
* Zwraca **kopię**, nie modyfikuje wejścia. To ważne: gdyby modyfikowała
  w miejscu, wywołujący dostałby zmieniony obiekt bez ostrzeżenia.

### `enums.py` — słownik pojęć aplikacji

```python
class RelationshipType(StrEnum):
    BOARD_MEMBER_OF = "board_member_of"     # osoba -> spółka (zarząd)
    PARTNER_IN = "partner_in"               # wspólnik -> spółka
    REGISTERED_AT = "registered_at"         # podmiot -> adres
```

`StrEnum` (Python 3.11+) to wyliczenie, którego elementy **są** napisami.
Dzięki temu `RelationshipType.PARTNER_IN == "partner_in"` jest prawdą i można
je wstawiać wprost do SQL-a czy JSON-a, a jednocześnie mieć podpowiadanie
w edytorze i wyłapanie literówki przez `mypy`.

Nazewnictwo krawędzi czyta się jak zdanie: `ŹRÓDŁO --TYP--> CEL`, czyli
`OSOBA --partner_in--> SPÓŁKA`.

### `graph_budget.py` — ile grafu wolno zwrócić

Graf ma 6,4 mln krawędzi. Gdyby zapytanie „pokaż powiązania" nie miało limitu,
jedno kliknięcie mogłoby wciągnąć pół bazy. Ten moduł trzyma limity:

```python
@dataclass(slots=True)
class GraphBudget:
    max_depth: int = 2
    max_nodes: int = 250
    fanout_per_node: int = 25
```

**`@dataclass`** to dekorator, który generuje za nas `__init__`, `__repr__`
i porównywanie — zamiast pisać konstruktor ręcznie, deklaruje się pola.

**`slots=True`** mówi Pythonowi, żeby nie tworzył dla obiektu słownika
atrybutów. Obiekt zajmuje mniej pamięci i szybciej się do niego sięga, ale nie
można mu dopisać pola, którego nie zadeklarowano. W tym projekcie to zaleta:
literówka w nazwie pola wywala się od razu, zamiast po cichu tworzyć nowy
atrybut.

**`frozen=True`** (używane np. w `task_queue.py`) idzie krok dalej — obiektu
nie da się zmienić po utworzeniu. Przydatne wszędzie tam, gdzie coś ma być
faktem, a nie zmienną.

### Pozostałe

* `identity.py` — kiedy dwa rekordy to ta sama osoba/firma (entity resolution).
* `graph_shape.py` — zwijanie węzłów, które powtarzają informację.
* `map_grid.py` — arytmetyka siatki mapy (patrz §7).
* `registry_values.py` — słowniki wartości z rejestrów.

---

## 4. Warstwa `db/` — jak wyglądają tabele

`models.py` (635 linii) opisuje tabele w Pythonie, w stylu SQLAlchemy 2.0:

```python
class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[uuid_pk]
    entity_type: Mapped[EntityType] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    degree: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

`Mapped[str]` to adnotacja typu, z której SQLAlchemy odczytuje, że kolumna nie
może być pusta; `Mapped[str | None]` znaczyłoby, że może. Czyli **typ w Pythonie
i ograniczenie w bazie to jedna deklaracja**, nie dwie, które mogą się rozjechać.

### Dwie decyzje modelowe, które warto zrozumieć

**Hybryda „encja + tabela szczegółów".** Jest jedna tabela wierzchołków
(`entities`) i osobne tabele atrybutów (`companies`, `people`, `addresses`)
związane z nią relacją jeden-do-jednego. Dzięki temu `relationships` ma dwa
zwykłe klucze obce i przechodzenie po grafie jest jednym zapytaniem — a przy
tym nie tracimy typów kolumn ani ograniczeń.

**Bitemporalność.** Każdy fakt ma **cztery** znaczniki czasu:

| kolumna | znaczy |
|---|---|
| `valid_from` / `valid_to` | kiedy fakt **obowiązywał w rzeczywistości** |
| `recorded_at` / `superseded_at` | kiedy **my się o nim dowiedzieliśmy** |

Po co? Bo to są różne rzeczy. Prezes mógł zostać odwołany w marcu, a my
dowiedzieliśmy się w czerwcu. Bez rozdzielenia tych osi nie da się odpowiedzieć
na pytanie „co wiedzieliśmy w maju".

Konsekwencja praktyczna: **nic nie kasujemy i nic nie nadpisujemy**. Zmiana
faktu to ustawienie `superseded_at` na starym wierszu i dopisanie nowego.

---

## 5. Warstwa `repositories/` — czytanie danych

Tu mieszkają zapytania odczytowe i pisane są **surowym SQL-em**, nie przez ORM:

```python
_BY_EXACT_NAME = text("""
    SELECT e.id, e.entity_type, e.display_name, e.degree, ...
    FROM entities e
    WHERE e.normalized_name = :normalized
    ORDER BY score DESC
    LIMIT :limit
""")
```

**Dlaczego nie ORM?** Przechodzenie po grafie przez ORM oznacza pętlę, w której
każdy krok to osobne zapytanie (problem „N+1"). Przy grafie o zadanej głębokości
to setki zapytań zamiast jednego. Do **zapisu** ORM jest wygodny i jest używany;
do **odczytu grafu** — nie.

`text()` z nazwanymi parametrami (`:normalized`) to zapytanie parametryzowane:
wartości nigdy nie są sklejane z napisem, więc wstrzyknięcie SQL-a jest
niemożliwe.

### `entities.py` — wyszukiwarka etapowa (787 linii, największy plik)

Najciekawszy kawałek w projekcie. Wyszukiwanie idzie **etapami, od najtańszego
do najdroższego**, i zatrzymuje się, gdy zbierze dość wyników:

1. identyfikator (NIP/KRS/REGON) — jeżeli wpisano cyfry
2. dokładna nazwa znormalizowana
3. prefiks do granicy słowa
4. zbiór słów (indeks pełnotekstowy)
5. dowolny prefiks
6. nazwisko
7. podobieństwo trigramowe — **setki milisekund**, więc na końcu

Powód jest zmierzony, nie wymyślony: przy 9,5 mln encji trigramowy operator
`%` na indeksie GIN zwraca stratną bitmapę i zapytanie trwa 1,7–4,3 s.
Pierwsze etapy odpowiadają w 2–6 ms.

```python
def take(new_rows: list[Any]) -> None:
    for row in new_rows:
        if row["id"] not in seen:
            seen.add(row["id"])
            rows.append(row)
```

**Funkcja zagnieżdżona w funkcji** — Python na to pozwala, a taka funkcja widzi
zmienne z otoczenia (`seen`, `rows`). To wygodne dla drobnego pomocnika, który
nie ma sensu poza tym jednym miejscem. Nazywa się to *domknięcie* (closure).

`set` (`seen`) to zbiór — sprawdzenie „czy już jest" kosztuje tyle samo przy
dziesięciu i przy milionie elementów, w odróżnieniu od listy.

---

## 6. Warstwa `api/v1/` — HTTP

Ma być **cienka**: zwalidować wejście, zawołać repozytorium, zmapować wynik.
Żadnej logiki biznesowej.

```python
@router.get("/clusters", response_model=MapViewOut)
async def get_clusters(
    session: SessionDep,
    south: Annotated[float, Query(ge=-90, le=90)],
    zoom: Annotated[int, Query(ge=1, le=20)] = 7,
) -> MapViewOut:
```

**`Annotated[float, Query(ge=-90, le=90)]`** — typ plus metadane. FastAPI czyta
z tego, że parametr jest liczbą z zakresu −90..90, i **sam** odrzuca złe
żądania odpowiedzią 422, zanim funkcja się uruchomi. Walidacji nie pisze się
ręcznie.

**`SessionDep`** to skrót zdefiniowany w `api/deps.py`:

```python
SessionDep = Annotated[AsyncSession, Depends(get_session)]
```

To *wstrzykiwanie zależności*: FastAPI widzi `Depends(...)`, woła
`get_session()`, wstawia wynik jako argument i po zakończeniu żądania sprząta
połączenie. Funkcja endpointu nie wie, skąd sesja się bierze — co znaczy, że
w testach da się podstawić inną.

**`async def`** — funkcja asynchroniczna. Gdy czeka na odpowiedź bazy, oddaje
sterowanie, żeby serwer mógł obsłużyć inne żądanie. Przy pracy zdominowanej
przez czekanie na wejście-wyjście (a taka to jest) daje to znacznie więcej niż
wątki.

---

## 7. Mapa — przykład decyzji „kiedy liczyć", nie „jak szybko"

Warto prześledzić, bo pokazuje sposób myślenia o wydajności.

Zadanie: pokazać 1,9 mln adresów na mapie. Dwa i pół miliona znaczników nie ma
prawa trafić do przeglądarki, więc grupujemy je w siatkę i zwracamy liczności
komórek.

Pierwsza działająca wersja liczyła to zapytaniem przy **każdym przesunięciu
mapy** — 1,8 s. Plan zapytania pokazał dwie przyczyny: złączenie z `entities`
wymuszało skan 9,5 mln wierszy, a grupowanie po wyrażeniu było dla planisty
nieprzejrzyste (szacował 356 tys. grup, faktycznych było 723).

**Rozwiązaniem nie było szybsze zapytanie, tylko inna pora jego wykonania.**
Ta agregacja nie zależy od żądania: siatka jest stała, dane zmieniają się przy
imporcie. Liczenie jej przy każdym ruchu myszy to powtarzanie tej samej pracy.

Więc: jeden poziom jest **przeliczony** (`address_cells`, 297 tys. komórek po
0,005 stopnia), a poziomy zgrubniejsze zwijają się z niego w locie.

```python
def zwielokrotnienie(cell: Decimal) -> int:
    """Ile komórek bazowych mieści się w boku komórki dla danego przybliżenia."""
    iloraz = cell / SIATKA_BAZOWA
    if iloraz != iloraz.to_integral_value():
        raise ValueError(f"Bok {cell} nie jest wielokrotnością {SIATKA_BAZOWA}")
    return int(iloraz)
```

**Dlaczego `Decimal`, a nie `float`?** Bo `0.2 / 0.005` w arytmetyce
zmiennoprzecinkowej wychodzi 39,999…, a `int()` z tego to 39. Siatka
przesunięta o jedną komórkę — i nic tego nie zgłasza. `Decimal` liczy
dziesiętnie, dokładnie tak, jak człowiek na kartce.

Ta sama pułapka wraca przy zapytaniach: kolumny współrzędnych są typu
`numeric(9,6)`, a sterownik `asyncpg` zakoduje Pythonowego `float` w pełnym
rozwinięciu binarnym. `54.37967199999999` nie równa się `54.379672`, więc
zapytanie zwraca **zero wierszy bez żadnego błędu**.

---

## 8. Warstwa `etl/` — skąd biorą się dane

Najbardziej rozbudowana część. Trzy poziomy:

| poziom | co robi | przykład |
|---|---|---|
| `etl/fetching/` | odporność: ponawianie, limit tempa, bezpiecznik | `client.py` |
| `etl/sources/` | „jak rozmawiać z tym konkretnym rejestrem" | `mf_whitelist.py` |
| `etl/*_pipeline.py` | „co z tymi danymi zrobić" | `ceidg_pipeline.py` |

### `etl/fetching/` — dlaczego to jest osobno

Bo bez tego każdy nowy klient rejestru wymyślałby własny sposób na ponawianie.
Reguła jest twarda: **nowy klient nie pisze własnego retry**, tylko używa
`ResilientClient` i dopisuje profil do `profiles.py`:

```python
SourceKind.CEIDG: SourceProfile(
    rate_per_second=900 / 3600,   # zmierzone z nagłówków: 1000 zapytań / 60 min
    concurrency=1,
    retry=_CAREFUL,
)
```

Ta jedna linijka ma historię: profil miał wcześniej `5.0`, wzięte z sufitu.
Przebieg dostał `429 Too Many Requests` po 930 zapytaniach — rejestr **podaje**
swój limit w nagłówkach `x-rate-limit-*`, tylko nikt ich nie przeczytał.

### `etl/sources/` — jeden moduł na rejestr

Zadaniem tych modułów jest **wyłącznie** rozmowa z API i zamiana odpowiedzi na
struktury Pythona. Nie dotykają bazy.

```python
def czytaj_punkty(sciezka: Path) -> Iterator[PunktAdresowy]:
    ...
    for zdarzenie, element in kontekst:
        ...
        yield PunktAdresowy(city=..., latitude=..., longitude=...)
```

**`yield` zamiast `return`** robi z funkcji *generator*: zwraca elementy po
jednym, na żądanie, zamiast zbudować całą listę w pamięci. Tu jest to konieczne
— plik GML województwa ma 690 MB, a punktów jest 8,6 mln. Lista zjadłaby
pamięć; generator przetwarza po jednym.

`Iterator[PunktAdresowy]` w adnotacji mówi, że funkcja zwraca właśnie taki
strumień.

### `etl/*_pipeline.py` — co zrobić z danymi

Tu jest zapis do bazy, obsługa wznawiania i statystyki. Wzorzec, który się
powtarza:

```python
async with factory() as session, session.begin():
    ...
```

To **dwa menedżery kontekstu w jednej linii**. `with` gwarantuje sprzątanie
nawet przy wyjątku: `factory()` daje sesję i ją zamknie, `session.begin()`
otwiera transakcję i albo ją zatwierdzi, albo wycofa. Bez tego trzeba by pisać
`try/finally` ręcznie i pamiętać o każdej ścieżce wyjścia.

**Statystyki jako dataclass**, nie jako luźne liczniki:

```python
@dataclass(slots=True)
class PartnershipStats:
    checked: int = 0
    edges_created: int = 0
    errors: int = 0
    aborted: str = ""
```

Pole `aborted` ma swoją historię. Pierwszy przebieg po wyczerpaniu limitu
przemielił **118 501 partii nie robiąc nic** i zameldował sukces, bo pętla
łapała błąd i szła dalej. Teraz źródło, które przestało odpowiadać, zatrzymuje
przebieg — licznik błędów, na który nikt nie reaguje, jest szumem.

### Wznawianie

Pełny przebieg po CEIDG to 96 455 zapytań i kilka dób. Każde przerwanie nie może
oznaczać startu od zera, więc przebieg zapisuje ostatni przetworzony numer:

```python
for poczatek in range(0, len(cele), ROWNOLEGLE):
    paczka = cele[poczatek : poczatek + ROWNOLEGLE]
    wyniki = await asyncio.gather(*(client.fetch(c.nip) for c in paczka),
                                  return_exceptions=True)
    ...
    stats.last_nip = paczka[-1].nip     # dopiero po całej paczce
```

**`asyncio.gather(...)`** uruchamia kilka zapytań **równolegle** i czeka na
wszystkie. `*(...)` rozpakowuje generator na osobne argumenty.
`return_exceptions=True` sprawia, że błąd jednego nie przerywa reszty — wraca
jako obiekt wyjątku w wyniku.

Dlaczego paczkami, a nie strumieniem? Bo punktem wznowienia jest **ostatni
przetworzony numer**, a przy odpowiedziach kończących się poza kolejnością
„ostatni" przestałby znaczyć „wszystko przed nim gotowe".

Efekt: przebieg sekwencyjny wykorzystywał 453 zapytania na godzinę
z dozwolonych 900 — resztę zjadało czekanie na sieć. Po zmianie: 796.

---

## 9. Cztery niezmienniki — reguły, których nie wolno złamać

Zapisane w `CLAUDE.md`, każdy ma testy. Naruszenie to defekt krytyczny, nie
zwykły błąd.

| | reguła | dlaczego |
|---|---|---|
| **N1** | fakty są niezmienne | bez tego nie da się odtworzyć, co wiedzieliśmy wczoraj |
| **N2** | każda krawędź ma pochodzenie | „skąd to wiecie" musi mieć odpowiedź |
| **N3** | budżet zapytania jest w kontrakcie | ciche przycięcie wyniku to kłamstwo |
| **N4** | zbieżność nazwisk nie scala osób | „Jan Kowalski" to nie jest identyfikator |

N3 warto rozwinąć, bo jest nieoczywisty. Jeżeli zapytanie zwraca 2000 z 5000
pasujących wierszy, odpowiedź **musi to powiedzieć** (`meta.truncated`).
Wynik, który wygląda na kompletny, a nie jest, jest gorszy niż błąd — bo nikt
się nie dowie.

---

## 10. Testy — trzy poziomy

```
tests/unit/          bez bazy, ~0,2 s, muszą działać wszędzie
tests/integration/   z Postgresem, oznaczone @pytest.mark.integration
+ testy mutacyjne    na warstwie domain/
```

**Test nazywa regułę, nie metodę.** Nie `test_score_person_pair`, tylko
`test_identical_names_alone_never_auto_merge_people`. Z nazwy ma być widać,
co przestanie być prawdą, gdy test spadnie.

### Testy mutacyjne — po co, skoro są zwykłe

Narzędzie (`mutmut`) celowo psuje kod: zmienia `>=` na `>`, `+` na `-`, kasuje
linie. Potem uruchamia testy. **Jeżeli testy nadal przechodzą, to znaczy, że
nie sprawdzały tej reguły** — wykonywały linię, ale nie patrzyły na wynik.

To nie jest teoria. W tym projekcie bramka mutacyjna:

* wyłapała, że nowa reguła domenowa nie ma **żadnego** testu (49 mutantów
  nietkniętych);
* pokazała, że trzy kolejne wywołania `strip()` o zachodzących zbiorach znaków
  **wzajemnie się maskowały** — usunięcie któregokolwiek nie zmieniało wyniku,
  czyli były zbędne, a nie nieprzetestowane;
* znalazła martwy `return`, do którego żadne wejście nie docierało.

Ostatnie dwa to nie brak testu, tylko **nadmiarowy kod**. Naprawą było
uproszczenie, nie dopisanie asercji.

---

## 11. Pułapki, które już raz kosztowały debugowanie

Warte przeczytania przed pierwszą zmianą — wszystkie przeszły przez lokalne
testy i wywróciły się później.

**`Result.rowcount` nie istnieje.** Potrzebny rzut:
`cast(CursorResult[Any], result).rowcount`.

**asyncpg nie wywnioskuje typu parametru użytego tylko w porównaniu z NULL-em.**
`:param IS NOT NULL` wymaga `CAST(:param AS text)`. Lint tego nie widzi, bo to
surowy SQL; wyłapuje dopiero test integracyjny.

**`text()` parsuje parametry także w komentarzach SQL.**
`-- CAST(:x AS interval)` tworzy niezwiązany parametr `x`.

**`timedelta(0)` jest fałszywe.** `retry_in or default` cicho zamienia
natychmiastowe ponowienie w domyślne opóźnienie. To ogólna cecha Pythona:
`0`, `""`, `[]`, `{}` i `None` są wszystkie fałszywe, więc `x or y` nie znaczy
„jeśli x jest podane".

**Funkcja używająca `get_etl_sessionmaker()` pracuje na bazie produkcyjnej
także wtedy, gdy wywoła ją test.** Silnik ETL ma własne połączenie i fixture go
nie przechwyci. Pominięcie tego raz scaliło 12 665 encji w produkcyjnej bazie
z poziomu testu. Każda taka funkcja musi mieć wariant przyjmujący sesję.

**Drugie `asyncio.run()` w jednej komendzie** dostaje połączenia przypięte do
zamkniętej pętli zdarzeń.

---

## 12. Frontend w skrócie

Next.js (App Router) + React. Trzy strony: wyszukiwarka, mapa, profil podmiotu.
Graf rysuje Cytoscape.js, mapę — Leaflet.

Jedna klasa błędu wystąpiła tam dwa razy i warto ją znać: **biblioteki mierzą
swój kontener w momencie utworzenia**. Jeżeli w tej chwili kontener nie ma
jeszcze docelowego rozmiaru — a nie ma go, dopóki nie ustali się układ strony —
to Leaflet zwraca prostokąt bliski punktowi, a Cytoscape upycha wszystkie węzły
w rogu.

Objaw jest paskudny, bo **nic tego nie zgłasza**: konsola czysta, kanwa ma
poprawne wymiary, po prostu nic nie widać. Lekarstwo w obu przypadkach to
`ResizeObserver`, który po zmianie rozmiaru przelicza i dopasowuje widok.

---

## 13. Od czego zacząć czytanie

Proponowana kolejność, gdyby ktoś chciał wejść w kod:

1. `domain/enums.py` — słownik pojęć, 80 linii, czyta się w pięć minut
2. `db/models.py` — kształt danych
3. `api/v1/search.py` + `repositories/entities.py` — jedno pełne żądanie od
   HTTP do SQL-a
4. `etl/fetching/profiles.py` — skąd i jak szybko wolno pobierać
5. `etl/partnership_pipeline.py` — najmniejszy kompletny import (od zapytania,
   przez pobranie, po zapis i wznawianie)

Dla zrozumienia **dlaczego** coś jest tak, a nie inaczej:
[`docs/09-dziennik.md`](09-dziennik.md) — zapis decyzji podejmowanych wtedy,
gdy coś zaskoczyło.
