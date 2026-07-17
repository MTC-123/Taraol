FROM python:3.12-slim

WORKDIR /app
COPY --from=astral/uv:0.11.29 /uv /uvx /bin/
ENV UV_CONCURRENT_DOWNLOADS=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY agents ./agents
RUN uv sync --frozen --no-dev
CMD ["uv", "run", "--no-sync", "python", "-m", "agents.alpha.main"]
