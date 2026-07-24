# otel-agent-kit

**Drop-in OpenTelemetry instrumentation for multi-agent systems.** Any Python agent
gets gen_ai-semconv spans, cross-process `traceparent`, cost-per-call rollup, and the
security/quality overlays that power a self-defending agent mesh — in ~3 lines,
framework-neutral, no content ever captured.

Extracted from [Agent Mesh Radar](../../README.md); this is the reusable library the
demo is built on.

## Install

```sh
pip install otel-agent-kit            # core: OTel SDK + gRPC OTLP + pyyaml
pip install "otel-agent-kit[http]"    # add the HTTP OTLP exporter
```

Point it at a collector with the standard `OTEL_EXPORTER_OTLP_ENDPOINT`.

## Three lines

```python
from otel_agent_kit import instrument

kit = instrument("planner")                                    # OTel wired, zero config
with kit.agent("planner", conversation_id) as _a, kit.chat("gpt-4.1-mini") as c:
    c.record(input_tokens=n_in, output_tokens=n_out)           # gen_ai span + cost rollup
```

`instrument()` installs one `ParentBased(ALWAYS_ON)` provider per process
(idempotent), a batching OTLP exporter, W3C trace-context **and** baggage
propagation, and the bundled price table. `chat(...).record(...)` takes plain token
counts — no dependency on any LLM SDK's result type.

## Cross-process traceparent

```python
from otel_agent_kit import inject_into, extract_from

inject_into(headers)            # on send: adds traceparent + baggage
ctx = extract_from(headers)     # on receive: rebuild the distributed trace
```

Agents that propagate `traceparent` render as a live topology in SigNoz's Service
Map with zero custom UI.

## Overlays (one extra call)

```python
kit.mark_injection("jailbreak")            # tag the active span; this service = origin
with kit.taint_scope(taint):               # downstream hops inherit the taint (blast radius)
    ...
kit.flag_output("hallucination", span)     # mark bad-output origin for provenance
```

```python
from otel_agent_kit import find_cycles, find_directed_cycles, origin_of_bad_output
from otel_agent_kit.breaker import get_registry, edge_key

find_cycles(trace_spans)                       # per-trace loops
find_directed_cycles(edges, min_repeats=1)     # cross-conversation loops
origin_of_bad_output(trace_spans, kit.names)   # who produced bad output, who consumed it

registry = get_registry()
if registry.allow(edge_key("writer", "critic")):
    ...                                        # per-edge circuit breaker
```

## Bundled SigNoz dashboards

```python
from otel_agent_kit import assets
assets.list_dashboards()          # ['conversation-budget', 'cost-per-agent', 'cost-per-edge']
assets.dump_dashboards("./out")   # write JSON for one-click SigNoz import
```

Or from the CLI: `otel-agent-kit dump-dashboards ./out`.

## Configuration

Everything is overridable; defaults make the 3-line path work with no env vars.

| Setting | Default | Env |
|---|---|---|
| `service_namespace` | `agents` | `OAK_SERVICE_NAMESPACE` |
| `attr_namespace` | `agentmesh` | `OAK_ATTR_NAMESPACE` |
| `provider_name` | `unknown` | `OAK_PROVIDER_NAME` |
| `exporter` | `grpc` | `OTEL_EXPORTER_OTLP_PROTOCOL` |
| `endpoint` | — | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| pricing | bundled | `OAK_PRICING_FILE` |

```python
kit = instrument("planner", attr_namespace="myco", cost_model={"gpt-4.1-mini": {"input_per_1k": 0.0004, "output_per_1k": 0.0016}})
```

## Guarantees

- `ParentBased(ALWAYS_ON)` sampling — the mesh never breaks from independent head sampling.
- `traceparent` on every hop; project attributes namespaced, gen_ai attributes stable.
- **No content capture** — scanners return a boolean + category enum, never the text.

## Roadmap

- `[a2a]` extra: bundled JSON-RPC transport with breaker-aware client/server.
- `integrations/`: auto-instrument adapters for the OpenAI Agents SDK and LangChain.

Apache-2.0.
