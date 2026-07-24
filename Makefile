.PHONY: up down test lint fmt demo demo-full verify-demo terraform-validate dashboard-validate

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

# demo-full is the SUBMISSION demo: the real closed loop through SigNoz
# (telemetry -> SigNoz alert rule -> notification webhook -> controller -> breaker
# -> agent_paused -> SigNoz verification). Requires a SigNoz API key + the one-time
# notification-channel UI step (see docs/DEMO.md).
demo-full:
	uv run python scripts/demo.py --full

# demo is the offline, no-secret FALLBACK for repository reviewers: it verifies the
# real loop-watcher signal, then delivers the Alertmanager-shaped webhook itself
# (the substitution is printed loudly). Do not record this as the submission demo.
demo:
	uv run python scripts/demo.py

verify-demo: demo

terraform-validate:
	terraform -chdir=signoz/terraform init -backend=false
	terraform -chdir=signoz/terraform validate

dashboard-validate:
	uv run python scripts/validate_artifacts.py
