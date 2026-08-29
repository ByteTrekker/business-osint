.DEFAULT_GOAL := help
COMPOSE := docker compose

help: ## Lista poleceń
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up: ## Uruchamia bazę, API i frontend
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

test-integration: ## Testy integracyjne (wymagają Postgresa)
	$(COMPOSE) exec api pytest tests -m integration -q

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

audit: ## Podatności w zależnościach
	cd backend && .venv/bin/pip-audit --skip-editable
	cd frontend && npm audit --audit-level=high

migration-check: ## Czy modele SQLAlchemy zgadzają się z migracjami
	cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic check

commits: ## Konwencja commitów w bieżącej gałęzi
	./scripts/check-commits.sh

check: lint typecheck coverage commits ## Bramki CI możliwe do uruchomienia bez bazy

psql: ## Konsola SQL
	$(COMPOSE) exec db psql -U osint -d osint

bench: ## Generuje syntetyczny graf i mierzy czas zapytań
	$(COMPOSE) exec api python -m business_osint.cli seed && \
	$(COMPOSE) exec db psql -U osint -d osint -f /dev/stdin < ops/bench.sql

.PHONY: help up down logs migrate revision seed test test-integration lint format \
        typecheck coverage audit migration-check commits check psql bench
