.PHONY: up down test lint fmt demo verify-demo terraform-validate dashboard-validate

up:
	docker compose --profile mcp up -d

down:
	docker compose down -v

test:
	uv run pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

demo:
	uv run python scripts/demo.py

verify-demo: demo

terraform-validate:
	terraform -chdir=signoz/terraform init -backend=false
	terraform -chdir=signoz/terraform validate

dashboard-validate:
	uv run python scripts/validate_artifacts.py
