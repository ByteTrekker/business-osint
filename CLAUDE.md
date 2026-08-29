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
make lint               # ruff
make typecheck          # mypy strict (backend) + tsc (frontend)
make check              # lint + typecheck + testy — to, co sprawdza CI
make psql               # konsola SQL
```

**Przed pushem uruchom `make check`.** `mypy` jest w trybie strict, a frontend ma
`tsc --noEmit` w CI — sam `pytest` i `ruff` tego nie wyłapią. Typowe pułapki,
które już raz przeszły przez lokalne testy i wywróciły CI:
`dict` bez parametrów typu (`disallow_any_generics`), `Result.rowcount`
(trzeba `cast(CursorResult[Any], ...)`), oraz nietypowane callbacki Cytoscape.

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
