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

lint: ## Ruff + mypy
	cd backend && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests

psql: ## Konsola SQL
	$(COMPOSE) exec db psql -U osint -d osint

bench: ## Generuje syntetyczny graf i mierzy czas zapytań
	$(COMPOSE) exec api python -m business_osint.cli seed && \
	$(COMPOSE) exec db psql -U osint -d osint -f /dev/stdin < ops/bench.sql

.PHONY: help up down logs migrate revision seed test test-integration lint psql bench
