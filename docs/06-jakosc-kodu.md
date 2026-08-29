# Pipeline jakości

Dokument opisuje, **co** sprawdzamy, **dlaczego akurat to** i **jak uruchomić
to lokalnie**. Zasada porządkująca: każda bramka w CI musi mieć odpowiednik
możliwy do uruchomienia na własnej maszynie. Bramka, której nie da się
odtworzyć lokalnie, zamienia się w loterię — commit, push, czekanie, poprawka.

## Bramki

| bramka | narzędzie | co wyłapuje | lokalnie |
|---|---|---|---|
| konwencja commitów | `scripts/check-commits.sh` | komunikaty niezgodne z Conventional Commits, subject > 72 znaków | `make commits` |
| styl (Python) | `ruff check` | błędy, nieużywane importy, reguły bezpieczeństwa (zestaw `S`, odpowiednik bandita) | `make lint` |
| formatowanie (Python) | `ruff format --check` | rozjazd formatowania — usuwa dyskusje o stylu z code review | `make lint` |
| typy (Python) | `mypy --strict` | brakujące adnotacje, `Any` przeciekające przez granice, niezgodne typy | `make typecheck` |
| zachowanie | `pytest tests/unit` | regresje w logice domenowej, bez bazy, ~0,3 s | `make test` |
| pokrycie warstwy domenowej | `pytest --cov-fail-under=90` | reguła domenowa dopisana bez testu | `make coverage` |
| migracje | `alembic upgrade head` | migracja, której nie da się nałożyć | `make migrate` |
| zgodność modeli z migracjami | `alembic check` | rozjazd między modelami SQLAlchemy a schematem w bazie | `make migration-check` |
| integracja | `pytest -m integration` | błędny SQL, złe typy parametrów, błędy widoku i indeksów | `make test-integration` |
| podatności (Python) | `pip-audit` | znane CVE w zależnościach | `make audit` |
| styl (TS) | `eslint` | błędy Reacta/Next, reguły dostępności | `make lint` |
| formatowanie (TS) | `prettier --check` | j.w. dla frontendu | `make lint` |
| typy (TS) | `tsc --noEmit` | błędy typów, których nie wyłapie build | `make typecheck` |
| build | `next build` | błędy, które ujawniają się dopiero przy kompilacji produkcyjnej | — |
| podatności (npm) | `npm audit --audit-level=high` | znane CVE w zależnościach frontendu | `make audit` |
| analiza bezpieczeństwa | CodeQL (`python`, `javascript-typescript`) | przepływ danych: czy wejście użytkownika trafia do SQL, ścieżki pliku itd. | — |
| aktualność zależności | Dependabot | przeterminowane zależności, cotygodniowo | — |

```bash
make check   # wszystko, co da się sprawdzić bez bazy
make test-integration migration-check   # reszta, wymaga Postgresa
```

## Dlaczego akurat te bramki

**`alembic check` jest tu najważniejszą nieoczywistą pozycją.** Migracja `0001`
jest pisana ręcznie (autogenerate nie radzi sobie z indeksami częściowymi,
`INCLUDE` ani widokami), więc modele i schemat mogą się rozjechać po cichu.
Przy pierwszym uruchomieniu ta bramka wykryła trzy realne defekty:

1. cztery indeksy istniały tylko w migracji, nie w modelach — kolejny
   `--autogenerate` chciałby je skasować;
2. nazwy `CHECK` były prefiksowane dwukrotnie (`ck_entities_ck_entities_...`),
   bo do już zaprefiksowanej nazwy dokładała się konwencja nazw;
3. PostgreSQL normalizuje `'epoch'::date` do `'1970-01-01'::date` przy zapisie
   wyrażenia indeksu, więc model i baza nigdy nie byłyby zgodne.

Żadnego z nich nie wykryłyby testy — wszystkie ujawniłyby się dopiero przy
tworzeniu kolejnej migracji, czyli w najgorszym możliwym momencie.

**Testy integracyjne są nieusuwalne, mimo że są wolniejsze.** Zapytania grafowe
są pisane surowym SQL-em, którego mypy nie widzi. Przykład z tego projektu:
asyncpg nie potrafi wywnioskować typu parametru występującego wyłącznie
w porównaniu `$1 IS NOT NULL` i zwraca `AmbiguousParameterError`. Kod przechodził
lint, typy i wszystkie testy jednostkowe — wyszukiwarka po prostu nie działała.

**Próg pokrycia dotyczy tylko `domain/`, nie całości.** Warstwa domenowa nie ma
I/O i musi być testowalna bez bazy — tam 90% jest wymogiem sensownym (obecnie
jest 100% z pokryciem gałęziowym). Wymuszanie progu na całym `src/` mierzyłoby
pokrycie kodu I/O testami jednostkowymi, których tam z definicji nie ma, i
zachęcałoby do pisania testów udających integrację.

**`ruff format --check` jest bramką, a nie sugestią**, bo formatowanie w code
review to najdroższy możliwy sposób prowadzenia dyskusji o stylu.

## Czego świadomie nie ma

| pominięte | powód |
|---|---|
| bandit | reguły `S` w ruff pokrywają ten sam zakres, bez drugiego narzędzia |
| black / isort | ruff robi jedno i drugie, szybciej |
| coverage gate na `src/` | patrz wyżej — mierzyłby niewłaściwą rzecz |
| mutation testing (`mutmut`) | wartościowe dla `domain/`, ale wolne; wchodzi, gdy warstwa domenowa się ustabilizuje |
| testy E2E (Playwright) | interfejs jest jeszcze zbyt zmienny; wchodzą po ustaleniu przepływów MVP |
| SonarQube / Codecov | dodatkowa usługa i sekret w repo; progi trzymamy w `pyproject.toml` |
| skan sekretów w workflow | GitHub ma skanowanie sekretów włączone domyślnie dla repozytoriów publicznych, a `pre-commit` ma `detect-private-key` |

## Bramki lokalne (pre-commit)

```bash
pip install pre-commit && pre-commit install --install-hooks
pre-commit install --hook-type commit-msg
```

`pre-commit` jest **węższy niż CI** i tak ma pozostać — ma trwać ułamek sekundy.
Sprawdza: białe znaki, poprawność YAML/TOML, wielkość plików, klucze prywatne,
`ruff` z autopoprawką, `ruff format`, blokadę commitów na `main` oraz konwencję
komunikatu commita.

Pełny zestaw uruchamia `make check`.

## Kiedy podnosić progi

| próg | dziś | podnieść, gdy |
|---|---|---|
| pokrycie `domain/` | 90% | nigdy poniżej; stan faktyczny to 100% |
| pokrycie `repositories/` | brak | po dodaniu testów integracyjnych dla wyszukiwarki — wtedy 70% |
| `npm audit` | `--audit-level=high` | po wdrożeniu produkcyjnym → `moderate` |
| mutation testing | brak | po ustabilizowaniu entity resolution |

Progi podnosimy razem z dopisaniem testów, nigdy „na zapas” — próg, którego nikt
nie potrafi spełnić, zostaje wyłączony przy pierwszym pilnym wdrożeniu i już nie
wraca.
