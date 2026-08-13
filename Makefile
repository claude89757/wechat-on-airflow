PYTHON ?= python3.12
VENV ?= .venv
BIN := $(VENV)/bin
RUNTIME_PYTHON := $(shell if [ -x "$(BIN)/python" ]; then printf '%s' "$(BIN)/python"; else printf '%s' "$(PYTHON)"; fi)
COMPOSE_BIN ?= $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; elif docker-compose version >/dev/null 2>&1; then echo docker-compose; else echo "docker compose"; fi)
LOCAL_SECRET_DIR := $(abspath .local/secrets)
COMPOSE := AIRFLOW_SECRET_DIR=$(LOCAL_SECRET_DIR) $(COMPOSE_BIN)

.PHONY: setup local-secrets webapp-setup webapp-check format lint typecheck test test-dags compose-config sender-config \
	smoke verify deploy deploy-check production-health rollback-check db-cleanup-check \
	phone-diagnose wechat-quiesce airflow-resume image sender-image sender-deploy sender-health sender-diagnose sender-screenshot sender-recover

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e '.[dev]'
	$(MAKE) webapp-setup

webapp-setup:
	cd webapp && npm ci

local-secrets:
	PYTHONPATH=scripts $(RUNTIME_PYTHON) scripts/prepare_local_secrets.py

webapp-check:
	cd webapp && npm test
	cd webapp && npm run check:worker
	cd webapp && npm run build
	cd webapp && npm run test:sites

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

compose-config: local-secrets
	$(COMPOSE) config --quiet
	$(COMPOSE_BIN) -f docker-compose.sender.yml config --quiet

sender-config:
	$(COMPOSE_BIN) -f docker-compose.sender.yml config --quiet

smoke:
	PYTHONPATH=src $(BIN)/python scripts/check_active_components.py

verify: lint typecheck test webapp-check compose-config smoke test-dags

deploy:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py airflow deploy $(DEPLOY_ARGS)

deploy-check: local-secrets
	PYTHONPATH=src $(BIN)/python scripts/deploy_check.py --dry-run

production-health:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py airflow health

rollback-check: local-secrets
	PYTHONPATH=src $(BIN)/python scripts/rollback_check.py --dry-run

db-cleanup-check:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py airflow db_cleanup_check

phone-diagnose:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py airflow phone_diagnose

wechat-quiesce:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py airflow wechat_quiesce \
		--target-commit $(TARGET_COMMIT)

airflow-resume:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py airflow airflow_resume \
		--target-commit $(TARGET_COMMIT)

sender-deploy:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py sender deploy $(DEPLOY_ARGS)

sender-health:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py sender health

sender-diagnose:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py sender device_diagnose

sender-screenshot:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py sender ui_screenshot

sender-recover:
	PYTHONPATH=scripts $(BIN)/python scripts/github_production.py sender device_recover

image: local-secrets
	$(COMPOSE) build airflow-cli

sender-image:
	$(COMPOSE_BIN) -f docker-compose.sender.yml build
