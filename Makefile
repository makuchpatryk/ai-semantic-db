.PHONY: up down obs-up obs-down migrate revision check lint types arch unit test-integration

up:
	docker compose up -d --wait

down:
	docker compose down

obs-up:
	docker compose --profile obs up -d otel-lgtm

obs-down:
	docker compose --profile obs down

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision -m "$(m)"

check: lint types arch unit

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

types:
	uv run mypy

arch:
	uv run lint-imports

unit:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration
	uv run alembic check
