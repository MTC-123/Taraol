# Architecture

Taraol is layered so you adopt only what you need. Every layer speaks standard OpenTelemetry —
no proprietary protocol anywhere in the stack.

```
                    Application
                         │
             @agent   @chat   @tool         (or the context-manager tier)
                         │
                  Taraol SDK  (src/taraol/)
                         │
         OpenTelemetry instrumentation
         ParentBased(ALWAYS_ON) · W3C traceparent + baggage · gen_ai semconv
                         │
              OTLP exporter (gRPC / HTTP)
                         │
                      SigNoz
                         │
         ┌───────────────┴──────────────┐
         │                              │
     Dashboards / UI              Query API / ClickHouse
                                        │
                                        ▼
                                 Watcher service ──> Controller service
                                 (detection extra)   (pause / break / audit)
```

## Two instrumentation tiers

**Decorator tier** — `@agent` / `@chat` / `@tool`. Fewest lines; the common path. `@chat` reads
tokens, cost, and (opted-in) content straight off the returned SDK response.

**Context-manager tier** — `with kit.agent(name, conversation_id), kit.chat(model) as c: ...`.
For fine control: per-request conversation ids, span handles for taint marking and state
hashes, streaming, custom LLM clients. Same spans, same telemetry.

The quickstarts (`main.py`, `main_2.py`, `demos/trip_planner/`) use the decorator tier; the
distributed mesh (`demos/research_mesh/`) uses decorators for chat/tool and the CM tier for its
per-request root span. Pick the tier that fits.

## Package layout

```
src/taraol/
  setup.py facade.py decorators.py   instrumentation core: instrument(), @agent/@chat/@tool
  config.py semconv.py attributes.py settings, gen_ai keys, namespaced project attrs
  cost.py                            price table + cost rollup (direct / downstream split)
  capture.py replay.py               opt-in content capture + conversation replay
  experiments.py experiment_report.py AgentLab: builder, HealthScore, summary/diff read path
  cycle.py breaker.py taint.py       analysis + self-defense primitives
  provenance.py guardrail.py quality.py
  llm.py assets.py cli.py            bundled LLM client, dashboard/deploy assets, operator CLI
  integrations/a2a/   [a2a]          JSON-RPC agent-to-agent transport with traceparent
  detection/          [detection]    watcher (reads SigNoz) + controller (enforces)
  mcp/                [mcp]          grounded incident explain over the SigNoz MCP server
  tools/search.py     [search]      real web search (Tavily) + fake provider
  data/                              bundled dashboards + the Foundry SigNoz deploy
demos/                               reference apps built only on the public API
tests/                               offline unit tests (in-memory exporter, fake providers)
```

## Design rules

- **Content-free by default.** No prompt/output/tool text unless `OAK_CAPTURE_CONTENT` is on;
  captured text is truncated with a marker.
- **`gen_ai.*` keys are vendor-neutral** — never re-namespaced. Project attributes go through
  `AttrNames` (default namespace `agentmesh`).
- **Sampler is `ParentBased(ALWAYS_ON)`**; W3C traceparent + baggage injected/extracted on
  every hop.
- **Core install stays minimal** (otel + pyyaml). Web deps (fastapi/httpx/mcp) live in extras.

## Cross-process tracing

A request keeps one trace id across HTTP, the A2A protocol, and multiple containers/machines.
The A2A client injects traceparent + baggage on send and the server extracts on receive, so a
request that starts on one machine and finishes on another appears as a single trace — which is
what lets SigNoz draw the live Service Map.

## Reproducible backend

`src/taraol/data/signoz/` ships a committed Foundry deployment (`casting.yaml` +
`casting.yaml.lock` + rendered `pours/`). `taraol signoz up` boots it; `foundryctl cast -f
casting.yaml` reproduces it exactly. See [foundry.md](foundry.md).
