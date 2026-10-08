VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

# The test suite drops and recreates APPTS_CORE_TEST_DB on every run, so this
# points at kalens' own container (port 5433), never pets-appts' 5432.
export APPTS_CORE_DATABASE_URL ?= postgresql://postgres:postgres@localhost:5433/postgres

.PHONY: help venv install db-up db-down db-logs test verify compare-schema compare-openapi lint clean

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

verify: test compare-schema compare-openapi ## everything: suite + both equivalence checks

compare-schema: ## diff our migrated schema against pets-appts' own
	$(VENV)/bin/python scripts/compare_schema.py

compare-openapi: ## diff our API surface against pets-appts' openapi.json
	$(VENV)/bin/python scripts/compare_openapi.py

lint: ## byte-compile everything as a syntax check
	$(PY) -m compileall -q src tests && echo "syntax ok"

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
