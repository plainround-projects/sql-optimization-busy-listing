# Commands for the lab. `make up`, `make db`, `make run`, `make test`, `make down` are all you need.
-include .env
PGHOST ?= localhost
PGPORT ?= 55432
PGUSER ?= lab
PGPASSWORD ?= lab
PGDATABASE ?= lab
APP_PORT ?= 8142
export PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE APP_PORT

# How SQL files reach the server. CI overrides this with a plain `psql` on the runner.
PSQL ?= docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U $(PGUSER) -d $(PGDATABASE)

VENV := .venv
PYTHON := $(VENV)/bin/python

.PHONY: up db run test serve psql down

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --quiet -r requirements.txt
	touch $@

up:
	docker compose up -d --wait

# Schema, seed (about 30 seconds), then the queries the lesson runs by hand.
db:
	$(PSQL) < sql/001_schema.sql
	$(PSQL) < sql/002_seed.sql
	$(PSQL) < sql/003_queries.sql

# Replays the lesson: starts the app, runs the same load three times (naive, N+1 fixed, keyset),
# ranks queries from pg_stat_statements each time, and writes the notes file.
run: $(VENV)/.installed
	$(PYTHON) -m scripts.run_lesson

test: $(VENV)/.installed
	$(PYTHON) -m pytest

# The app on http://localhost:$(APP_PORT)/orders for poking at by hand.
serve: $(VENV)/.installed
	$(PYTHON) -m uvicorn app.main:app --port $(APP_PORT)

psql:
	docker compose exec db psql -U $(PGUSER) -d $(PGDATABASE)

# -v removes the volume too, so the next `make up` starts from an empty database.
down:
	docker compose down -v
