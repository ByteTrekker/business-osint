# CLAUDE.md

Instrukcje dla Claude Code pracującego w tym repozytorium.

## Czym jest ten projekt

Graf powiązań polskich firm i osób, budowany na publicznych rejestrach
(KRS, REGON, CEIDG, CRBR). Odpowiada na pytanie „jak ta firma jest powiązana
z innymi firmami i osobami”, a nie „co jest wpisane o tej firmie”.

Zanim zaproponujesz zmianę architektoniczną, przeczytaj
[docs/04-zalozenia-projektu.md](docs/04-zalozenia-projektu.md) i właściwy ADR.
Decyzje w `docs/adr/` mają zapisane **warunki rewizji** — jeżeli warunek nie jest
spełniony, decyzja obowiązuje.

## Komendy

```bash
make up                 # postgres + api + frontend (docker compose)
make seed               # dane demonstracyjne, działa bez dostępu do rejestrów
make test               # testy jednostkowe, bez bazy, ~0.2 s
make test-integration   # testy z Postgresem
make lint               # ruff + eslint + prettier
make format             # automatyczne formatowanie
make typecheck          # mypy strict (backend) + tsc (frontend)
make coverage           # testy z progiem pokrycia domain/ (90%)
make audit              # pip-audit + npm audit
make commits            # konwencja Conventional Commits
make check              # wszystko, co da się sprawdzić bez bazy
make migration-check    # alembic upgrade + alembic check (wymaga Postgresa)
make psql               # konsola SQL
```

**Przed pushem uruchom `make check`, a przy zmianach w modelach dodatkowo
`make migration-check` i `make test-integration`.** Pełny opis bramek:
[docs/06-jakosc-kodu.md](docs/06-jakosc-kodu.md).

Pułapki, które już raz przeszły przez lokalne testy i wywróciły CI albo runtime:

* `dict` bez parametrów typu — mypy strict ma `disallow_any_generics`.
* `Result.rowcount` nie istnieje na `Result[Any]`; potrzebny
  `cast(CursorResult[Any], result).rowcount`.
* asyncpg **nie wywnioskuje typu parametru** użytego wyłącznie w porównaniu
  z NULL (`:param IS NOT NULL`) — trzeba `CAST(:param AS text)`. Lint i mypy
  tego nie widzą, bo to surowy SQL; wyłapuje dopiero test integracyjny.
* Migracje pisane ręcznie rozjeżdżają się z modelami. `alembic check` jest
  bramką w CI — nowy indeks w migracji musi trafić też do `__table_args__`.
* PostgreSQL normalizuje `'epoch'::date` do `'1970-01-01'::date` w wyrażeniach
  indeksów — model musi używać tej samej postaci.

Backend ma lokalny venv w `backend/.venv` (poza gitem):

```bash
cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/unit -q
cd backend && .venv/bin/ruff check src tests
```

Migracje: `alembic revision --autogenerate -m "opis"`, potem **przeczytaj
wygenerowany plik** — autogenerate nie wykrywa indeksów częściowych, `INCLUDE`
ani widoków i trzeba je dopisać ręcznie.

## Mapa katalogów

```
backend/src/business_osint/
  domain/        czysta logika, ZERO I/O — normalizacja, entity resolution, budżet grafu
  db/            modele SQLAlchemy 2.0 (Mapped[], DeclarativeBase)
  repositories/  zapytania odczytowe — surowy SQL przez text()
  api/v1/        warstwa HTTP, cienka: walidacja + mapowanie na schematy
  schemas/       kontrakty pydantic (wejście/wyjście API)
  etl/           klienci rejestrów, mappery, loadery
backend/tests/unit/         bez bazy — muszą działać wszędzie
backend/tests/integration/  z Postgresem, oznaczone @pytest.mark.integration
frontend/src/               Next.js App Router + Cytoscape.js
docs/adr/                   decyzje architektoniczne z warunkami rewizji
```

Nowy kod trafia do warstwy zgodnej z jego zależnościami. Jeżeli funkcja
potrzebuje bazy, nie należy do `domain/`.

## Niezmienniki — naruszenie to defekt krytyczny

Każdy ma pokrycie w testach. Jeżeli zmiana wymaga złamania któregoś, to jest
zmiana architektoniczna wymagająca ADR, a nie zwykły commit.

1. **Fakty są niezmienne.** Zero `UPDATE` na `relationships`, zero `DELETE`.
   Zmiana faktu = `superseded_at` na starym wierszu + nowy wiersz.
2. **Każda krawędź ma pochodzenie.** Wstawienie do `relationships` bez wpisu
   w `relationship_sources` jest błędem loadera.
3. **Budżet zapytania jest w kontrakcie API.** `meta.truncated` musi odzwierciedlać
   rzeczywistość. Ciche przycięcie wyniku to defekt krytyczny.
4. **Zbieżność imienia i nazwiska nie scala osób.** Automatyczne scalenie wymaga
   twardego identyfikatora albo dwóch niezależnych sygnałów.

## Konwencje kodu

* **Python 3.12+**, `from __future__ import annotations`, pełne adnotacje typów
  (mypy strict). Dataclasses z `slots=True`, `frozen=True` gdzie to możliwe.
* **Dokumentacja i komentarze po polsku.** Komentarz wyjaśnia **dlaczego**, nie
  **co** — „co” ma wynikać z nazw. Docstring modułu mówi, po co moduł istnieje
  i jaką decyzję realizuje.
* **ORM do zapisu, surowy SQL do odczytu grafu.** Traversal przez ORM to N+1
  w pętli. Zapytania grafowe piszemy przez `text()` z nazwanymi parametrami.
* **Dialekt asyncpg używa paramstyle `numeric_dollar`** — znak `%` w SQL-u
  (operator `pg_trgm`) NIE jest podwajany. Przy przeniesieniu na psycopg trzeba
  go zapisać jako `%%`.
* **Logika domenowa bez I/O.** Wszystko, co da się przetestować bez bazy, ma być
  testowalne bez bazy.
* Formatowanie: `ruff`, linia 100 znaków.

## Testy

* Test ma nazywać **regułę**, nie metodę:
  `test_identical_names_alone_never_auto_merge_people`, nie `test_score_person_pair`.
* Mappery źródeł testujemy na **zamrożonych fixture'ach** — zmiana schematu
  po stronie urzędu ma dawać czerwony test, nie ciche pustoszenie grafu.
* Testy jednostkowe nie dotykają sieci ani bazy. Bez wyjątków.
* Nowa reguła domenowa bez testu nie wchodzi.

## Czego nie proponować

Poniższe zostały rozważone i odrzucone z uzasadnieniem. Propozycja ich dodania
wymaga wskazania, że **warunek rewizji z ADR został spełniony**.

| pomysł | dlaczego nie | ADR |
|---|---|---|
| Neo4j / baza grafowa | skala nie wymaga; nie rozwiązuje ER, bitemporalności ani provenance | ADR-0001 |
| GraphQL zamiast REST | trzy kształty odpowiedzi; zagnieżdżony traversal to wektor DoS | ADR-0004 |
| Kafka / event-driven ingestion | rejestry nie mają webhooków — brak źródła zdarzeń | docs/00 §8 |
| Elasticsearch | `pg_trgm` wystarcza do kilku milionów nazw | docs/00 §17 |
| mikroserwisy / Kubernetes | jeden model danych, jeden zespół | docs/00 §19 |
| rekurencyjne CTE do traversalu | brak sensownego limitu rozgałęzień w członie rekurencyjnym | ADR-0004 |
| przepisanie API na Go/Rust | API jest I/O-bound — to nie jest wąskie gardło | ADR-0005 |

## Git: commity, gałęzie i pull requesty

**Język: angielski.** Dotyczy komunikatów commitów, nazw gałęzi oraz tytułów
i opisów pull requestów. Historia gita i PR-y są artefaktem inżynierskim
o dłuższym życiu niż projekt i mogą trafić do odbiorcy spoza zespołu.

**Dokumentacja, komentarze i docstringi zostają po polsku** — patrz sekcja
„Konwencje kodu”. To nie jest niekonsekwencja: `docs/` i kod opisują dziedzinę
(rejestry, KRS, formy prawne), gdzie polska terminologia jest precyzyjniejsza,
a git opisuje zmiany w kodzie.

### Format commita — Conventional Commits

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Typy:** `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`,
`chore`, `revert`.

**Scope** (opcjonalny, ale zalecany) — moduł, którego zmiana dotyczy:
`api`, `db`, `domain`, `graph`, `etl`, `krs`, `frontend`, `docs`, `ci`, `deps`.

**Subject:** tryb rozkazujący, małą literą, bez kropki na końcu, do 72 znaków.
„add hub suppression”, nie „added” ani „adds”.

**Body:** wyjaśnia **dlaczego**, nie **co** — „co” widać w diffie. Zawijanie
na 72 znakach. Jeżeli zmiana dotyka niezmiennika albo decyzji z ADR, wskaż to
wprost. Body jest opcjonalne przy zmianach trywialnych i obowiązkowe przy
zmianach w modelu danych, traversalu i entity resolution.

**Footer:** `BREAKING CHANGE: <opis>` dla zmian łamiących kontrakt API lub
schemat bazy, `Refs #<numer>` dla powiązanych zgłoszeń.

Przykłady:

```
feat(graph): suppress hub expansion above configured degree

A virtual-office address with 5k companies made depth-3 traversal return
half the database. Nodes above the degree threshold are now returned but
not expanded, and meta.suppressed_hubs reports how many were skipped.

Refs ADR-0004.
```

```
fix(etl): close relationships that disappeared from the source

KRS does not always provide a removal date. Facts missing from a fresh
document are now closed with the import date and flagged as inferred,
instead of silently staying active.
```

```
docs(adr): add language specialisation thresholds
```

### Nazwy gałęzi

`<type>/<krótki-opis-po-angielsku>`, np. `feat/entity-resolution-queue`,
`fix/trigram-index-not-used`, `docs/data-sources`.

### Pull requesty

* **Tytuł** — dokładnie ta sama konwencja co subject commita.
* **Opis po angielsku**, w strukturze:
  1. **Why** — problem lub potrzeba, nie lista plików.
  2. **What changed** — istotne decyzje, nie streszczenie diffa.
  3. **Invariants** — czy PR dotyka N1–N4; jeżeli któryś jest łamany, wymagany
     jest ADR.
  4. **Verification** — co zostało uruchomione i **czego nie uruchomiono**.
  5. **Deliberate omissions** — świadome pominięcia z uzasadnieniem.

**Sekcja Verification musi być uczciwa.** Napisanie „tested” bez wskazania,
czego nie sprawdzono, jest gorsze niż jej brak — czytelnik podejmuje decyzję
o scaleniu na podstawie tego, co uznaje za zweryfikowane.

PR pozostaje w stanie **draft** dopóki istnieje znany, nierozwiązany warunek
blokujący — i ten warunek ma być wymieniony w opisie z nazwy.

## Dane osobowe

* **PESEL nigdy jawnie** — wyłącznie `pesel_hash()` z pepperem z sekretów.
* Nie dodawaj pól z danymi osobowymi bez wpisu w
  [docs/03-prawo-i-ryzyko.md](docs/03-prawo-i-ryzyko.md).
* Dane demonstracyjne w `etl/seed_demo.py` są **zmyślone**. Nie wstawiaj tam
  prawdziwych osób ani prawdziwych numerów KRS/NIP istniejących podmiotów.

## Przepisywanie komponentów na inne języki

Docelowo część systemu przechodzi na Rust (entity resolution) i Go (crawler) —
patrz [docs/05-strategia-wielojezykowa.md](docs/05-strategia-wielojezykowa.md)
i ADR-0005. Do tego czasu obowiązuje zasada: **nie wprowadzaj zależności, które
łamią granice modułów** opisane w tym dokumencie. Crawler komunikuje się
z systemem wyłącznie przez tabele Postgresa, entity resolution przez
`resolution_candidates` → `entity_merges`, traversal przez interfejs
`GraphRepository.neighborhood()`.
