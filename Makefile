VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

# The test suite drops and recreates KALENS_TEST_DB on every run, so this
# points at kalens' own container on 5433, away from the default 5432 that an
# application database is likely to be on.
export KALENS_DATABASE_URL ?= postgresql://postgres:postgres@localhost:5433/postgres

.PHONY: help venv install db-up db-down db-logs test verify lint clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## create the virtualenv
	python3 -m venv $(VENV)

install: venv ## install the package and its test extras, editable
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e ".[test]"

db-up: ## start postgres (port 5433) and wait for it
	docker compose up -d db
	@until docker compose exec -T db pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
	@echo "kalens-db ready on 5433"

db-down: ## stop postgres and drop its volume
	docker compose down -v

db-logs: ## tail postgres logs
	docker compose logs -f db

test: ## run the suite against the reference host
	$(VENV)/bin/pytest -v

verify: lint test ## everything: syntax check + suite

lint: ## byte-compile everything as a syntax check
	$(PY) -m compileall -q src tests && echo "syntax ok"

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
