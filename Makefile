.DEFAULT_GOAL := help
COMPOSE := docker compose
DB_URL := postgresql+asyncpg://osint:osint@localhost:5432/osint

help: ## Lista poleceń
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

dev-api: ## Uruchamia API lokalnie (wymaga Postgresa na 5432)
	cd backend && BUSINESS_OSINT_DATABASE_URL=$(DB_URL) \
		.venv/bin/python -m uvicorn business_osint.main:app --reload --port 8000

dev-web: ## Uruchamia frontend lokalnie (wymaga działającego API)
	cd frontend && NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api/v1 npm run dev

db-local: ## Tworzy lokalną bazę i nakłada migracje (Postgres z brew)
	createdb -O osint osint 2>/dev/null || true
	cd backend && BUSINESS_OSINT_DATABASE_URL=$(DB_URL) .venv/bin/alembic upgrade head

up: ## Uruchamia całość w Dockerze (niezweryfikowane — patrz README)
	$(COMPOSE) up -d --build

down: ## Zatrzymuje wszystko
	$(COMPOSE) down

logs: ## Logi API
	$(COMPOSE) logs -f api

migrate: ## Nakłada migracje
	$(COMPOSE) exec api alembic upgrade head

revision: ## Nowa migracja: make revision m="opis"
	$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"

seed: ## Ładuje dane demonstracyjne
	$(COMPOSE) exec api python -m business_osint.cli seed

test: ## Testy jednostkowe (bez bazy)
	cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/unit -q

# Uruchamiamy tak samo jak CI: natywnie, przeciwko lokalnemu Postgresowi.
# Poprzednia wersja szła przez `docker compose exec` i nie wykonała się ani
# razu — cel, który nigdy nie wystartował, jest gorszy niż jego brak, bo
# wygląda na pokrycie.
test-integration: ## Testy integracyjne (wymagają Postgresa)
	cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/integration -q -m integration

lint: ## Ruff + ESLint + Prettier
	cd backend && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
	cd frontend && npm run lint && npm run format:check

format: ## Automatyczne formatowanie (ruff + prettier)
	cd backend && .venv/bin/ruff check --fix src tests && .venv/bin/ruff format src tests
	cd frontend && npm run format

typecheck: ## mypy (backend, strict) + tsc (frontend)
	cd backend && .venv/bin/mypy src
	cd frontend && npm run typecheck

coverage: ## Testy jednostkowe z progiem pokrycia warstwy domenowej
	cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/unit -q \
		--cov=business_osint.domain --cov-report=term-missing --cov-fail-under=90

mutation: ## Testy mutacyjne warstwy domenowej
	cd backend && MUTMUT_BIN=.venv/bin/mutmut ../scripts/check-mutation.sh

audit: ## Podatności w zależnościach
	cd backend && .venv/bin/pip-audit --skip-editable
	cd frontend && npm audit --audit-level=high

migration-check: ## Czy modele SQLAlchemy zgadzają się z migracjami
	cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic check

commits: ## Konwencja commitów w bieżącej gałęzi
	./scripts/check-commits.sh

# Asercje na **danych**, nie na kodzie. Świadomie nie ma ich w `check` ani w CI:
# baza CI jest pusta po migracjach, więc kontrole przeszłyby tam zawsze i nie
# znaczyłyby nic. Sensu nabierają dopiero na prawdziwym zbiorze, dlatego
# uruchamia je operator po imporcie — i każda komenda importu na koniec sama.
data-check: ## Niezmienniki na danych w lokalnej bazie
	cd backend && PYTHONPATH=src .venv/bin/python -m business_osint.cli check-data

check: lint typecheck coverage mutation commits ## Bramki CI możliwe do uruchomienia bez bazy

check-db: migration-check test-integration data-check ## Bramki wymagające Postgresa

psql: ## Konsola SQL
	$(COMPOSE) exec db psql -U osint -d osint

# Pomiar przez kontrakt HTTP — jedyna rzecz, która nie zmienia się przy
# wymianie języka backendu albo bazy danych. `ops/bench.sql` pokazuje plany
# zapytań PostgreSQL i zostaje do strojenia indeksów, ale odpowiada na inne
# pytanie i przestaje działać po zmianie bazy.
bench: ## Mierzy wydajność przez API (wymaga działającego backendu)
	python3 ops/benchmark/run.py --out ops/benchmark/results/$(shell date +%Y%m%d-%H%M%S).json

bench-compare: ## Zestawia dwa przebiegi: make bench-compare PRZED=... PO=...
	python3 ops/benchmark/run.py --compare "$(PRZED)" "$(PO)"

bench-sql: ## Plany zapytań PostgreSQL — do strojenia indeksów, zależne od bazy
	$(COMPOSE) exec db psql -U osint -d osint -f /dev/stdin < ops/bench.sql

.PHONY: help dev-api dev-web db-local up down logs migrate revision seed test test-integration lint format \
        typecheck coverage mutation audit migration-check commits check check-db data-check psql bench bench-compare bench-sql
