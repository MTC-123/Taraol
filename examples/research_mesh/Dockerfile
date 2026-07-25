# Build context is the repo root (the taraol package lives at the root).
FROM python:3.12-slim
WORKDIR /app
COPY --from=astral/uv:0.11.29 /uv /uvx /bin/
ENV UV_CONCURRENT_DOWNLOADS=1
# Install the kit with the extras the mesh uses.
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system ".[a2a,detection,mcp,search,llm]"
COPY examples ./examples
ENV PYTHONPATH=/app/examples
CMD ["python", "-m", "research_mesh.agent"]
