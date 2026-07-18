PYTHON ?= python3.12
VENV ?= .venv
BIN := $(VENV)/bin
COMPOSE_BIN ?= $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; elif docker-compose version >/dev/null 2>&1; then echo docker-compose; else echo "docker compose"; fi)
COMPOSE := $(COMPOSE_BIN) --env-file .env.example

.PHONY: setup format lint typecheck test test-dags compose-config sender-config \
	smoke verify deploy deploy-check production-health rollback-check image sender-image

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e '.[dev]'

format:
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

typecheck:
	$(BIN)/mypy

test:
	PYTHONPATH=src $(BIN)/pytest -m 'not airflow'

test-dags: image
	$(COMPOSE) run --rm --no-deps --entrypoint python airflow-cli \
		/opt/airflow/project/scripts/check_dag_imports.py

compose-config:
	$(COMPOSE) config --quiet
	$(COMPOSE_BIN) -f docker-compose.sender.yml --env-file .env.example config --quiet

sender-config:
	$(COMPOSE_BIN) -f docker-compose.sender.yml --env-file .env.example config --quiet

smoke:
	PYTHONPATH=src $(BIN)/python scripts/check_active_components.py

verify: lint typecheck test compose-config smoke test-dags

deploy:
	PYTHONPATH=src $(BIN)/python scripts/deploy_airflow.py $(DEPLOY_ARGS)

deploy-check:
	PYTHONPATH=src $(BIN)/python scripts/deploy_check.py --dry-run

production-health:
	PYTHONPATH=src $(BIN)/python scripts/production_health.py --format json

rollback-check:
	PYTHONPATH=src $(BIN)/python scripts/rollback_check.py --dry-run

image:
	$(COMPOSE) build airflow-cli

sender-image:
	$(COMPOSE_BIN) -f docker-compose.sender.yml --env-file .env.example build
