FROM python:3.12-slim
WORKDIR /app
COPY --from=astral/uv:0.11.29 /uv /uvx /bin/
ENV UV_CONCURRENT_DOWNLOADS=1
# Install the kit (with the extras the mesh uses) + the example package.
COPY packages/otel-agent-kit /app/otel-agent-kit
RUN uv pip install --system "/app/otel-agent-kit[a2a,detection,mcp,search,llm]"
COPY examples /app/examples
ENV PYTHONPATH=/app/examples
CMD ["python", "-m", "research_mesh.agent"]
