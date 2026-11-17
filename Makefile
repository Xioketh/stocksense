# Shortcuts for common commands. Run "make <target>", e.g. "make up".
# (Makefile lines must be indented with a TAB, not spaces.)

API_DIR := services/api

.PHONY: up down logs migrate psql test-db test lint format check reset-db

up:            ## Build and start db + api in the background
	docker compose up -d --build db api

down:          ## Stop all containers (database data is kept)
	docker compose down

logs:          ## Follow the API logs
	docker compose logs -f api

migrate:       ## Apply database migrations inside the api container
	docker compose run --rm api alembic upgrade head

psql:          ## Open a psql shell on the local database
	docker compose exec db psql -U stocksense -d stocksense

test-db:       ## Start the separate test database
	docker compose up -d --wait db-test

test: test-db  ## Run the tests (on your laptop, against db-test)
	cd $(API_DIR) && pytest

lint:          ## Check code style and common bugs
	cd $(API_DIR) && ruff check . && ruff format --check .

format:        ## Auto-fix formatting and import order
	cd $(API_DIR) && ruff check --fix . && ruff format .

check: lint test   ## What CI will run

reset-db:      ## DANGER: delete the local database volume and start again
	docker compose down -v