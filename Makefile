.PHONY: setup lint type test test-integration up down

setup:
	uv sync

lint:
	uv run ruff check server tests spikes
	uv run ruff format --check server tests spikes

type:
	uv run mypy server

test:
	uv run pytest -q

test-integration:
	uv run pytest -q -m integration

up:
	docker compose up -d tigergraph

down:
	docker compose down
