.PHONY: up down test lint fmt demo

up:
	docker compose up -d

down:
	docker compose down -v

test:
	uv run pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

demo:
	@echo "PLAN 02 supplies the instrumented demo. Start the observability stack with: make up"


