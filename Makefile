.PHONY: test test-sqlite test-postgres lint lint-fix migrate migrate-new dev install clean e2e

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff
PYTEST := $(VENV)/bin/pytest
ALEMBIC := $(VENV)/bin/alembic

install:
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt -r requirements-dev.txt
	$(PIP) install cryptography

lint:
	$(RUFF) check app/ tests/

lint-fix:
	$(RUFF) check --fix app/ tests/

test: test-sqlite

test-sqlite:
	SKLAD_DATABASE_BACKEND=sqlite \
	SKLAD_DATABASE_URL=sqlite:///./test.db \
	SKLAD_DEV_AUTH_ENABLED=true \
	SKLAD_BACKGROUND_JOBS_ENABLED=false \
	$(PYTEST) tests/ -q --tb=short

test-postgres:
	SKLAD_DATABASE_BACKEND=postgresql \
	SKLAD_DATABASE_URL=postgresql://finalboss:finalboss_pass@localhost:5432/sklad_test \
	SKLAD_DEV_AUTH_ENABLED=true \
	SKLAD_BACKGROUND_JOBS_ENABLED=false \
	$(PYTEST) tests/ -q --tb=short

migrate:
	$(ALEMBIC) upgrade head

migrate-new:
	@read -p "Migration name: " name; \
	$(ALEMBIC) revision --autogenerate -m "$$name"

dev:
	SKLAD_DATABASE_BACKEND=sqlite \
	SKLAD_DATABASE_URL=sqlite:///./sklad_dev.db \
	SKLAD_DEV_AUTH_ENABLED=true \
	SKLAD_BACKGROUND_JOBS_ENABLED=false \
	$(VENV)/bin/uvicorn app.main:app --reload --port 8000

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -f test.db sklad_dev.db

e2e:
	PLAYWRIGHT_BROWSERS_PATH=/opt/sklad/.playwright PYTHONPATH=/opt/sklad $(PYTEST) tests/test_e2e_playwright.py -v
