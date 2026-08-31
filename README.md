# business-osint

Graf powiązań polskich firm i osób, budowany wyłącznie na publicznych rejestrach
(KRS, REGON, CEIDG, CRBR, zamówienia publiczne, dotacje UE).

Odpowiada na pytanie, na które wyszukiwarka KRS nie odpowiada:
**„Jak ta firma jest powiązana z innymi firmami i osobami?”**

```
Firma A ──prezes zarządu── Jan Kowalski ──udziałowiec── Firma B
                                                            │
                                                    prezes zarządu
                                                            │
                                                       Anna Nowak ──akcjonariusz── Firma C
```

## Czym to się różni od kolejnej wyszukiwarki KRS

| | wyszukiwarka rejestru | business-osint |
|---|---|---|
| jednostka wyniku | dokument (odpis) | węzeł w grafie |
| pytanie | „pokaż mi tę spółkę” | „pokaż mi otoczenie tej spółki” |
| czas | stan na dziś | stan na dowolny dzień (`?as_of=2022-01-01`) |
| pochodzenie danych | domyślne | każda krawędź ma źródło, datę pobrania i wskaźnik do miejsca w dokumencie |

## Uruchomienie

### Lokalnie (ścieżka zweryfikowana)

Wymaga PostgreSQL 17 i Node 22. Baza z Homebrew:

```bash
brew install postgresql@17 && brew services start postgresql@17
createuser -s osint 2>/dev/null; createdb -O osint osint
```

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[etl,dev]"
cd ../frontend && npm ci
```

```bash
make db-local    # migracje
make dev-api     # API na :8000   (osobny terminal)
make dev-web     # frontend na :3000 (osobny terminal)
```

Dane — jedno z dwóch:

```bash
cd backend && PYTHONPATH=src .venv/bin/python -m business_osint.cli seed
```

```bash
cd backend && PYTHONPATH=src .venv/bin/python -m business_osint.cli import-gleif
```

Pierwsze to dane demonstracyjne (zmyślone, działa bez sieci), drugie to prawdziwe
dane z GLEIF — ok. 36 tys. polskich firm i 1,1 tys. powiązań kapitałowych, ~4 minuty.

* Frontend: http://localhost:3000
* API i dokumentacja: http://localhost:8000/docs

### W Dockerze

```bash
cp .env.example .env
make up
make seed
```

> **Uwaga:** ścieżka dockerowa **nie została uruchomiona ani razu** — pliki
> `docker-compose.yml` i `Dockerfile` istnieją, ale demon Dockera był niedostępny
> w środowisku, w którym powstawał ten kod. Traktuj ją jako niezweryfikowaną.

```bash
make test        # testy jednostkowe (bez bazy, ~0.2 s)
make test-integration
make lint
```

## Architektura

```
Next.js 15 + Cytoscape.js
          │  REST (JSON)
FastAPI + SQLAlchemy 2 (async)
          │
     PostgreSQL 17          ← graf trzymany relacyjnie: entities + relationships
          ▲
Python ETL (httpx + Polars)
          │
KRS · REGON · CEIDG · CRBR · zamówienia · dotacje
```

Modularny monolit. Bez Neo4j, bez Kafki, bez mikroserwisów — decyzje i warunki
ich rewizji opisuje [docs/adr/](docs/adr/).

## Dokumentacja

| dokument | zawartość |
|---|---|
| [docs/04-zalozenia-projektu.md](docs/04-zalozenia-projektu.md) | **założenia projektu** — zakres, niezmienniki, definicja MVP, ryzyka |
| [docs/00-ocena-projektu.md](docs/00-ocena-projektu.md) | ocena pomysłu i stacku — odpowiedzi na 20 pytań projektowych |
| [docs/01-plan-dzialania.md](docs/01-plan-dzialania.md) | plan wdrożenia: 6 tygodni do MVP, potem skalowanie |
| [docs/02-zrodla-danych.md](docs/02-zrodla-danych.md) | rejestry, limity, licencje, strategia pobierania |
| [docs/03-prawo-i-ryzyko.md](docs/03-prawo-i-ryzyko.md) | RODO, prawo do bycia zapomnianym, ryzyko sprostowań |
| [docs/05-strategia-wielojezykowa.md](docs/05-strategia-wielojezykowa.md) | kiedy i które komponenty przechodzą na Rust/Go — progi, nie daty |
| [docs/08-lista-zadan.md](docs/08-lista-zadan.md) | co zrobione, co pilne, co zablokowane i na kim |
| [CLAUDE.md](CLAUDE.md) | instrukcje dla Claude Code: niezmienniki, konwencje, czego nie proponować |
| [docs/06-jakosc-kodu.md](docs/06-jakosc-kodu.md) | pipeline jakości — co sprawdzamy, dlaczego i jak uruchomić lokalnie |
| [docs/07-pobieranie-danych.md](docs/07-pobieranie-danych.md) | odporność pobierania, koszt źródeł, przyrostowość, granice Pythona |
| [docs/adr/](docs/adr/) | decyzje architektoniczne z warunkami rewizji |

## Struktura repozytorium

```
backend/
  src/business_osint/
    domain/         # czysta logika: normalizacja, entity resolution, budżet grafu
    db/             # modele SQLAlchemy 2.0
    repositories/   # zapytania (traversal, wyszukiwanie, profile)
    api/v1/         # warstwa HTTP
    etl/            # klienci rejestrów, mappery, loadery
  alembic/          # migracje
  tests/unit/       # bez bazy — uruchamiają się wszędzie
  tests/integration/# z Postgresem
frontend/           # Next.js App Router + Cytoscape.js
ops/                # benchmarki SQL
```

## Status

Wczesny etap. Działa: model danych, traversal z budżetem, wyszukiwarka,
provenance, mapper KRS, dane demonstracyjne, testy. Do zrobienia: pełny import
KRS, CRBR, entity resolution na skalę produkcyjną — patrz plan działania.

## Licencja i dane

Kod: MIT. Dane pochodzą z rejestrów publicznych i podlegają ich warunkom —
patrz [docs/02-zrodla-danych.md](docs/02-zrodla-danych.md).
