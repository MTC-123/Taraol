# Agent Mesh Radar

**See the hidden shape of a multi-agent system before a loop becomes an outage.**

![The five-agent mesh in SigNoz's Service Map](docs/evidence/service-map-full-mesh.png)
<!-- Swap for docs/evidence/demo-beat.gif once the live beat is recorded (docs/DEMO.md, Recovery and evidence). -->

Agent Mesh Radar models independently deployed agents as an OpenTelemetry **service
topology**, detects *non-converging* inter-agent loops, and closes the loop through
SigNoz-native alerting, per-edge budget enforcement, and evidence-grounded incident
explanation over MCP. `make demo-full` plays the whole incident through real SigNoz —
cost climbs, a runaway loop is detected, a SigNoz alert fires, the controller trips the
offending edge, cost flatlines, and an MCP post-mortem prints — in under 90 seconds. The
timed runbook is [docs/DEMO.md](docs/DEMO.md).

## How this is different

Existing agent-observability tools commonly focus on execution traces *inside one
application or framework* (e.g. an aggregated step graph across runs). Agent Mesh Radar
instead:

- **Models separate agent processes as a live topology.** Any HTTP agent service that
  propagates W3C `traceparent` shows up in SigNoz's Service Map, regardless of framework
  or vendor — the map is derived by SigNoz from ordinary trace parent/child relationships
  plus `service.name`, so no custom topology UI was built.
- **Distinguishes runaway loops from healthy iteration.** A generator/critic cycle is
  often intentional; we only flag a loop when an agent stops making progress (a repeated
  content-safe `state.hash`) or a cost/iteration budget is breached.
- **Closes the loop through SigNoz.** Detection queries the SigNoz Query API; a SigNoz
  alert rule fires the enforcement webhook; the controller trips a per-edge circuit
  breaker; the pause is verified back in SigNoz and explained through the SigNoz MCP
  server.

The work is the layer on top of the map: SigNoz-native runaway detection, per-edge cost
attribution, budget enforcement, and grounded explanation.

## Quickstart

### Prerequisites

- WSL 2 with a native Docker Engine and Docker Compose v2.20+ (the compose file uses
  `include`). SigNoz documents Docker Desktop on native Windows as unreliable for
  ClickHouse Keeper.
- At least 4 GB of Docker memory (8 GB recommended).
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for Python tooling.

Start the complete observability stack:

```sh
make up
```

`make up` starts the local official SigNoz MCP server. Then:

- `make demo-full` — the **submission demo**: the real closed loop through SigNoz
  (SigNoz alert rule → webhook → controller → per-edge breaker → verified pause →
  MCP post-mortem). Needs a SigNoz API key and the one-time notification-channel UI
  step; see [docs/DEMO.md](docs/DEMO.md).
- `make demo` — an offline, no-secret fallback for reviewers (substituted webhook,
  printed loudly).

Open [http://localhost:8080](http://localhost:8080). The bundled collector accepts OTLP gRPC
on `localhost:4317` and OTLP HTTP on `localhost:4318`.

```sh
make test
make lint
make down
```

If uv is unavailable, install it with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
For a limited pip-based fallback, create a Python 3.12 virtual environment and install the
development tools listed in `pyproject.toml`; the committed `uv.lock` remains the supported,
reproducible workflow.

## Layers

- **Instrumented-demo layer** (`agents/`) — independently runnable agents, one OTel service each.
- **Detection layer** (`detection/`) — reads telemetry to detect loops and budget breaches.
- **MCP-tool layer** (`mcp_tool/`) — explains observed loops through SigNoz.
- **Shared foundation** (`src/amr/`) — small cross-cutting helpers with no layer coupling.

Layers never import each other’s internals; they communicate through OTLP, HTTP, and SigNoz.
The full diagram and data flow are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md);
`tests/test_detection_architecture.py` enforces the boundary.

## Six signals, all live

Every SigNoz signal is exercised by the demo, not merely configured
(`tests/test_six_signals.py` asserts each one):

| Signal | How we use it |
|---|---|
| Traces | One distributed trace per conversation across five named agent services, W3C `traceparent` on every hop; the writer↔critic cycle is visible in the waterfall |
| Metrics | SigNoz-derived RED metrics (`signoz_calls_total`, `signoz_latency_bucket`) drive edge call-rate and P95 latency; custom counters for runaway loops, injections, and unhealthy edges |
| Logs | Trace-correlated `agent_reasoning`, `loop_detected`, `edge_broken`, and `agent_paused` events, filterable by `trace_id` and `conversation_id` |
| Dashboards | Three focused JSON exports: downstream cost by delegation edge, direct cost by agent, total cost by conversation |
| Alerts | Runaway-loop, budget, and edge-breaker rules plus a route policy, provisioned via the official Terraform provider; the firing webhook drives enforcement |
| MCP | `explain_this_loop(trace_id)` queries the official SigNoz MCP server and returns a grounded post-mortem (cycle, stalled iterations, cost, breaker action) |

Plus the headline: the **Service Map** itself is derived by SigNoz from trace
parent/child + `service.name` — the agent mesh renders with zero custom UI.

## SigNoz deployment

The repository commits Compose rendered by Foundry `v0.2.11` from
`deploy/signoz/casting.yaml`, with SigNoz pinned to `v0.128.0`. Normal development only needs
Docker Compose; see [the SigNoz deployment notes](deploy/signoz/README.md) to regenerate it.

## Cost dashboards

Import the three JSON files in `signoz/dashboards/` through **Dashboards → New dashboard →
Import JSON**. Each asks one question, keeps the primary KPI top-left, uses USD to four decimal
places, and applies green/amber/red thresholds. They intentionally use span attributes and Query
Builder sums, not a separate metric pipeline:

Cost is attributed with three explicit, unambiguous fields so values are never
double-counted:

- **`agentmesh.cost.direct_usd`** — cost of one agent's own chat call. `cost-per-agent.json`
  sums it by `service.name`; `conversation-budget.json` sums it by `gen_ai.conversation.id`,
  which is the **additive conversation total** and the authoritative budget figure.
- **`agentmesh.cost.downstream_usd`** — the callee subtree cost attributed to one delegation
  hop (`a2a.call` span). `cost-per-edge.json` sums it by `agentmesh.src` → `peer.service`.
  This is *per-delegation attribution and is deliberately not additive across edges* — the
  dashboard is titled accordingly.

An agent server returns `result._meta.cost_usd` (its direct chat cost plus every downstream
result cost); the caller writes that on the single hop span as `downstream_usd`. The edge
dashboard also includes P95 latency and call rate from SigNoz's derived
`signoz_latency_bucket` and `signoz_calls_total` metrics.

**Recorded submission demo uses a real model.** Set `AMR_LLM=gemini`,
`AMR_MODEL=gemini-2.0-flash`, and `GEMINI_API_KEY` so tokens, latency, and cost are
observed rather than manufactured. `AMR_LLM=fake` stays the default for tests and offline
reviewers (deterministic tokens); `AMR_LLM=real` supports any OpenAI-compatible endpoint.
Update `config/pricing.yaml` when changing the model; unknown models are tagged
`agentmesh.cost.unpriced=true` with a USD cost of `0.0`.

## Grounded loop explanation

`mcp_tool.server` exposes `explain_this_loop(trace_id)` for an MCP host. It calls the official
local SigNoz MCP server's read-only query tool—not ClickHouse or a direct SigNoz REST path—and
returns observed cyclic agents, A2A hop count, and direct-chat cost.
A pause action is deliberately `null` unless an audit-log lookup establishes it; the tool never
manufactures enforcement facts from topology alone.

Start the MCP endpoint with `uv run python -m mcp_tool.server`; its command-line equivalent is
`uv run amr explain <trace-id>`, which formats a readable incident post-mortem rather than dumping
raw JSON.

## Limitations and roadmap

Honest edges of the current build:

- **The submission demo (`make demo-full`) is the real closed loop.** Detection queries the
  SigNoz Query API, a SigNoz alert rule fires the webhook, the controller trips the edge,
  and the pause is verified back in SigNoz. `make demo` is an **offline, no-secret fallback**
  for repository reviewers: it verifies the real loop-watcher signal, then delivers the
  Alertmanager-shaped webhook itself (printed loudly). Do not record the fallback.
- **Notification channels are a provider gap.** The official SigNoz Terraform provider
  manages alert rules and route policies but not notification channels; the webhook channel
  is a one-time UI step, documented in [docs/DEMO.md](docs/DEMO.md).
- **Detection is polling, not streaming.** The watcher polls the SigNoz Query API (default
  every 5 s); detection latency is bounded by the poll interval plus ingest lag.

Roadmap: streaming detection, per-tenant budgets, an auto-resume policy (resume after N
minutes with a tightened budget), and richer progress scoring (semantic diff of successive
outputs rather than an exact state hash).

## Credits

Built on [SigNoz](https://signoz.io/),
[OpenTelemetry](https://opentelemetry.io/),
[A2A](https://a2a-protocol.org/), and
[OpenLLMetry](https://www.traceloop.com/openllmetry).

## License

Apache-2.0. See [LICENSE](LICENSE).

