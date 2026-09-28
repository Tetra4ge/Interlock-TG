.PHONY: setup lint type test up down

setup:
	uv sync

lint:
	uv run ruff check server tests spikes
	uv run ruff format --check server tests spikes

type:
	uv run mypy server

test:
	uv run pytest -q

up:
	docker compose up -d tigergraph

down:
	docker compose down
