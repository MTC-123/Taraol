# AGENTS.md — taraol

Drop-in OpenTelemetry instrumentation for multi-agent systems, shipped as a pip package.
Any Python agent gets gen_ai-semconv spans, cross-process `traceparent`, cost rollup, and
the analysis/enforcement toolkit (loop + injection + breaker + provenance) in ~3 lines. The
kit is the product; `examples/research_mesh/` is a reference app built on it.

## Layout
- `src/taraol/` — the package. Core (flat): `setup`, `facade`, `config`, `semconv`,
  `attributes`, `cost`, `propagation`, `events`, `capture`, `replay`, `cycle`, `breaker`,
  `taint`, `provenance`, `guardrail`, `quality`, `llm`, `assets`, `cli`, `experiments`
  (AgentLab builder/decorators), `experiment_report` (summary/diff read path, lazy `[detection]`).
  Optional subpackages (extras): `integrations/a2a` `[a2a]`, `detection/` `[detection]`,
  `mcp/` `[mcp]`, `tools/search.py` `[search]`. Bundled assets in `data/`.
- `examples/research_mesh/` — a 5-agent app + its SigNoz Foundry deploy + `compose.yaml`.
- `tests/` — offline unit tests (in-memory exporter, fake LLM/search).

## Commands
- Tests:   `uv run pytest`         (offline; fake providers, default settings)
- Lint:    `uv run ruff check .` / `uv run ruff format .`
- Build:   `uv build`              (wheel + sdist; data files ship)
- Example: `docker compose -f examples/research_mesh/compose.yaml up -d --build`

## Non-negotiable rules
- **Content-free by default.** No prompt/output/tool text is captured unless
  `OAK_CAPTURE_CONTENT` is on; captured text is always truncated with a marker. Keep the
  default path emitting zero content (a test asserts `gen_ai.input.messages` is absent).
- **`gen_ai.*` keys are vendor-neutral — never namespaced.** Project attributes go through
  `attributes.AttrNames` (default namespace `agentmesh`).
- Sampler is `ParentBased`; inject/extract W3C traceparent on every hop.
- Core install stays minimal (otel + pyyaml). Web deps live in extras only.
- Env vars are `OAK_*`; never commit secrets; update `.env.example` when adding one.

## Conventions
- Python 3.12, `uv`, `ruff`, `pytest`. Line length 100.
- One task = one commit. Tests pass before commit.
- New reusable capability → the kit; demo-specific usage → the example app.
