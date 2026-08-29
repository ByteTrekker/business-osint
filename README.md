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

```bash
cp .env.example .env
make up          # postgres + api + frontend
make seed        # dane demonstracyjne (bez dostępu do rejestrów)
```

* API i dokumentacja: http://localhost:8000/docs
* Frontend: http://localhost:3000

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
| [CLAUDE.md](CLAUDE.md) | instrukcje dla Claude Code: niezmienniki, konwencje, czego nie proponować |
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
