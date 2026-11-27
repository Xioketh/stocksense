# Shortcuts for common commands. Run "make <target>", e.g. "make up".
# (Makefile lines must be indented with a TAB, not spaces.)

API_DIR := services/api
WORKER_DIR := services/worker
ASSISTANT_DIR := services/assistant

.PHONY: up down logs logs-worker logs-assistant migrate assistant-db psql test-db test test-api test-worker test-assistant lint format check reset-db

up:            ## Build and start db + api + worker + assistant in the background
	docker compose up -d --build db api worker assistant

down:          ## Stop all containers (database data is kept)
	docker compose down

logs:          ## Follow the API logs
	docker compose logs -f api

logs-worker:   ## Follow the worker logs
	docker compose logs -f worker

logs-assistant: ## Follow the assistant logs
	docker compose logs -f assistant

migrate:       ## Apply database migrations inside the api container
	docker compose run --rm api alembic upgrade head

assistant-db:  ## Create the assistant's database on an EXISTING volume (safe to re-run)
	docker compose exec -T db psql -U stocksense -d postgres -f /docker-entrypoint-initdb.d/01-create-assistant-db.sql

psql:          ## Open a psql shell on the local database
	docker compose exec db psql -U stocksense -d stocksense

test-db:       ## Start the separate test database
	docker compose up -d --wait db-test

test: test-api test-worker test-assistant   ## Run all tests (on your laptop, against db-test)

test-api: test-db
	cd $(API_DIR) && pytest

test-worker: test-db
	cd $(WORKER_DIR) && pytest

lint:          ## Check code style and common bugs (all services)
	cd $(API_DIR) && ruff check . && ruff format --check .
	cd $(WORKER_DIR) && ruff check . && ruff format --check .
	cd $(ASSISTANT_DIR) && ruff check . && ruff format --check .

format:        ## Auto-fix formatting and import order (all services)
	cd $(API_DIR) && ruff check --fix . && ruff format .
	cd $(WORKER_DIR) && ruff check --fix . && ruff format .
	cd $(ASSISTANT_DIR) && ruff check --fix . && ruff format .

check: lint test   ## What CI will run

reset-db:      ## DANGER: delete the local database volume and start again
	docker compose down -v

test-assistant: test-db   ## Checkpoints go to stocksense_assistant_test on db-test
	cd $(ASSISTANT_DIR) && pytest