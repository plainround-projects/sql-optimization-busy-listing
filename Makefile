# make up | db | run | test | lint | down   (make help lists all)
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed

-include .env
export
PGHOST ?= localhost
PGPORT ?= 55432
PGUSER ?= lab
PGDATABASE ?= lab
APP_PORT ?= 8142

# How SQL files reach the server. CI overrides this with a plain `psql` on the runner.
PSQL ?= docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U $(PGUSER) -d $(PGDATABASE)

.PHONY: help install env up db reset run serve load health lint format test test-integration test-e2e audit check docker-build psql down clean

help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort

$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@

install: $(STAMP) ## create .venv from the lock file

env:
	@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }

up: env ## start PostgreSQL 18 and wait until it accepts connections
	docker compose up -d --wait

# Every file is safe to run twice: IF NOT EXISTS in the schema, a seed that skips tables that have rows.
db: ## schema, 100,000 customers and 1,000,000 orders (about 30 seconds the first time), the lesson's queries
	$(PSQL) < sql/001_schema.sql
	$(PSQL) < sql/002_seed.sql
	$(PSQL) < sql/003_queries.sql

reset: ## drop the lab's tables (make db rebuilds them)
	$(PSQL) < sql/reset.sql

run: $(STAMP) ## replay the lesson: the same load four times, ranking pg_stat_statements each time
	$(VENV)/bin/busy-listing-run

serve: $(STAMP) ## the listing on http://localhost:8142/orders in the foreground
	$(VENV)/bin/busy-listing-serve

load: $(STAMP) ## the load script against a running service: make load STRATEGY=naive
	$(VENV)/bin/busy-listing-load --strategy $(or $(STRATEGY),naive)

health: $(STAMP) ## exit 0 when PostgreSQL holds the seeded tables and pg_stat_statements
	$(VENV)/bin/busy-listing-health

lint: $(STAMP) ## ruff check, ruff format check, mypy, import-linter
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports

format: $(STAMP) ## apply ruff's formatting and safe fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

# Unit tests need no database. Coverage is reported for the package; domain and application must stay at 95% or more.
test: $(STAMP) ## unit tests with coverage (no PostgreSQL needed)
	$(PY) -m pytest tests/unit --cov=busy_listing --cov-report=term
	$(PY) -m coverage report --include='src/busy_listing/domain/*,src/busy_listing/application/*' --fail-under=95

test-integration: $(STAMP) ## the lesson's outcomes against the seeded database (make up db first)
	$(PY) -m pytest tests/integration -m integration

test-e2e: $(STAMP) ## the whole replay and the HTTP service (make up db first)
	$(PY) -m pytest tests/e2e -m e2e

audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock

check: lint test ## everything that needs no services

docker-build: ## build the container image of the command-line programs
	docker build -t sql-optimization-busy-listing:dev .

psql: ## an interactive psql session
	docker compose exec db psql -U $(PGUSER) -d $(PGDATABASE)

down: ## stop PostgreSQL and delete its data
	docker compose down -v

clean: down
	rm -rf $(VENV) logs .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage
