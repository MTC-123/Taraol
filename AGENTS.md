# AGENTS.md — Agent Mesh Radar

Multi-agent OpenTelemetry demo. Each agent is its own OTel service; the agent-to-agent
topology renders automatically in SigNoz's Service Map. We add cost-per-edge, loop
detection, alerts that pause a runaway agent, and an MCP "explain this loop" tool.

## Commands
- Start full stack:  `make up`      (SigNoz + collector + agents)
- Stop + wipe:       `make down`
- Tests:             `make test`    (pytest)
- Lint / format:     `make lint` / `make fmt`
- Run the demo:      `make demo`

## Architecture — THREE LAYERS, do not cross-import
- `agents/`     instrumented demo (one sub-package per agent = one `service.name`)
- `detection/`  loop/budget watcher + controller (reads SigNoz, never imports agents)
- `mcp_tool/`   "explain this loop" over the SigNoz MCP server
Shared helpers live in `src/amr/`. Layers talk only via OTLP/HTTP/SigNoz.

## Non-negotiable rules
- Every agent process sets a DISTINCT `OTEL_SERVICE_NAME`.
- Sampler MUST be `ParentBased` (never independent head sampling) — else the mesh breaks.
- On each agent-to-agent hop: INJECT W3C traceparent on send, EXTRACT on receive.
- GenAI spans use `gen_ai.*` semconv; opt in with
  `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`.
- Never commit secrets. `.env` is git-ignored; update `.env.example` when adding vars.
- Create SigNoz alerts via the UI or Terraform provider, NOT raw API POSTs.

## Conventions
- Python 3.12, `uv`, `ruff`, `pytest`. Line length 100.
- One task = one commit. Tests must pass before commit.


