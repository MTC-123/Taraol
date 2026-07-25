# otel-agent-kit

**Drop-in OpenTelemetry observability for multi-agent systems.** Any Python agent gets
gen_ai-semconv spans, cross-process `traceparent`, cost-per-call rollup, a live topology in
SigNoz, and an analysis + enforcement toolkit (runaway-loop detection, injection blast-radius,
per-edge circuit breaker, bad-output provenance) — plus opt-in **LangSmith-style step
inspection** — in ~3 lines. Framework-neutral, private by default.

> Built for the "Agents of SigNoz" hackathon. `examples/research_mesh/` is a full reference
> app (5 agents, real web search, real LLM) built entirely on this library.

## Install

```sh
pip install otel-agent-kit                      # core: OTel SDK + gRPC OTLP + pyyaml
pip install "otel-agent-kit[all]"               # + transport, detection, mcp, search, llm
```

Extras: `[a2a]` JSON-RPC agent transport · `[detection]` loop/breaker watcher + controller ·
`[mcp]` grounded incident explain · `[search]` Tavily web search · `[http]` HTTP OTLP exporter.

## Get a SigNoz backend

The kit is the OTLP **client** — it sends telemetry to a SigNoz backend (SigNoz doesn't come
in the wheel; it's a full platform). Pick one:

```sh
otel-agent-kit signoz up        # boot a local SigNoz (bundled Foundry deploy; pulls images once)
# → UI at http://localhost:8080, OTLP at http://localhost:4317
otel-agent-kit signoz down      # stop + wipe
```

…or point the kit at **SigNoz Cloud** / an existing collector via
`OTEL_EXPORTER_OTLP_ENDPOINT`. That's the only wiring the kit needs.

## Three lines

```python
from otel_agent_kit import instrument

kit = instrument("planner")                                     # OTel wired, zero config
with kit.agent("planner", conversation_id) as _a, kit.chat("gemini-2.5-flash") as c:
    c.record(input_tokens=n_in, output_tokens=n_out)            # gen_ai span + cost rollup
```

`instrument()` installs one `ParentBased(ALWAYS_ON)` provider (idempotent), a batching OTLP
exporter, W3C trace-context + baggage propagation, and the bundled price table. Agents that
propagate `traceparent` render as a live **Service Map** in SigNoz — no custom UI.

### …or one decorator

Prefer decorators? They wrap the same context managers — no subclassing, drop them on your
existing functions:

```python
from otel_agent_kit import instrument, agent, chat, tool, record_chat
instrument("planner")

@tool                       # execute_tool span (str return captured as the result)
def search(query): ...

@chat("gpt-4o")             # chat span; record usage/content from inside
def think(prompt):
    r = client.chat.completions.create(...)
    record_chat(input_tokens=r.usage.prompt_tokens, output_tokens=r.usage.completion_tokens)
    return r.choices[0].message.content

@agent(name="planner")      # invoke_agent span around the step
def plan(task):
    return think(search(task))
```

## LangSmith-style step inspection (opt-in)

Off by default — **no prompt/output/tool text is ever captured**. Turn it on with
`OAK_CAPTURE_CONTENT=on` (or `instrument(..., capture_content=True)`):

```python
with kit.chat("gemini-2.5-flash") as c:
    c.record(input_tokens=n_in, output_tokens=n_out)
    c.record_content(prompt=prompt, completion=output)          # gen_ai.input/output.messages

with kit.tool("search", arguments=query) as t:                  # any tool
    t.set_result(results_json)                                  # gen_ai.tool.call.result
```

Then reconstruct the per-agent chain — in the terminal or from code:

```sh
otel-agent-kit explain <trace-id> --replay        # each agent's input -> output -> tools
```
```python
from otel_agent_kit import replay
steps = replay.build_steps(spans)                 # framework-neutral, from trace rows
```

Captured text is truncated (default 12k/field) with an `agentmesh.content.truncated` marker.

## Cross-process traceparent

```python
from otel_agent_kit import inject_into, extract_from
inject_into(headers)        # on send: traceparent + baggage
ctx = extract_from(headers) # on receive: rebuild the distributed trace
```

## Analysis + enforcement toolkit

```python
from otel_agent_kit import find_cycles, find_directed_cycles, origin_of_bad_output
from otel_agent_kit.breaker import get_registry, edge_key

find_cycles(trace_spans)                      # per-trace loops
find_directed_cycles(edges, min_repeats=1)    # cross-conversation loops
origin_of_bad_output(spans, kit.names)        # who produced bad output, who consumed it
get_registry().allow(edge_key("a", "b"))      # per-edge circuit breaker

kit.mark_injection("jailbreak")               # taint the active span; spreads via baggage
kit.flag_output("hallucination", span)        # mark a bad-output origin
```

The `[detection]` extra ships a **watcher** (reads SigNoz, flags runaway loops / budget breaches
/ injection blast-radius / unhealthy edges) and a **controller** (alert webhook -> pause agent or
trip a per-edge breaker -> trace-correlated audit).

## AgentLab — compare operational behavior

Which prompt, model, or multi-agent workflow is cheaper, faster, and *safer to run*? AgentLab
tags every span + signal of a run with `experiment.id` / `experiment.variant` /
`experiment.run_id`, fires the same workload once per variant, and compares them on real
operational telemetry — cost, latency, tokens, **runaway loops, breaker trips, and failures** —
not answer quality. **SigNoz is the dashboard.**

```python
from otel_agent_kit import Experiment

(Experiment("battery-report", description="Gemini prompt A/B", author="Fraol")
    .variant("baseline", config={"loop_mode": "off"})
    .variant("runaway",  config={"loop_mode": "storm"})   # or .compare(baseline, runaway)
    .run(workload))                     # workload(variant) fires once per variant
```

One `.run()` = one **run_id** shared across its variants (Experiment → Run → Variant → Trace), so
repeated runs stay distinct. A variant that raises is recorded `status=failed` and the run keeps
going. Compare from the terminal — the CLI uses the SigNoz Query API when `SIGNOZ_API_KEY` is set,
else the ClickHouse fallback (same selection as the watcher):

```sh
otel-agent-kit experiment summary battery-report        # per-variant table + Operational Health
otel-agent-kit experiment diff <run1> <run2>            # cost/latency/loops/breaker deltas
```

```
variant              cost$   tokens  agents   avg ms  loops  breakers  fails  health
baseline            0.0120     1200       5     1800      0         0      0    99.6
runaway             0.0480     4800       5     5200      6         2      1    29.0
Highest Operational Health: baseline   (tune HealthScore to what you optimize)
```

`HealthScore` is pluggable (`100 − 10·loops − 5·breaker − 0.2·latency_s − 0.1·cost`, weights
overridable) and the "highest health" line is a factual read, not a universal winner. Import the
bundled **experiment-comparison** dashboard to see the same split by `experiment.variant` — widen
the time range to watch regression across runs. See
[`examples/research_mesh/experiment.py`](examples/research_mesh/experiment.py) for a runnable
baseline-vs-runaway on the 5-agent stack.

## Bundled SigNoz assets

```python
from otel_agent_kit import assets
assets.dump_dashboards("./out")     # cost-per-agent / cost-per-edge / conversation-budget /
                                    # experiment-comparison
assets.terraform_module_path()      # reusable alert-rule Terraform module
```
Or: `otel-agent-kit dump-dashboards ./out`.

## Configuration

Zero-config defaults; everything overridable via `instrument(...)`, `Settings`, or env.

| Setting | Default | Env |
|---|---|---|
| `attr_namespace` | `agentmesh` | `OAK_ATTR_NAMESPACE` |
| `capture_content` | `False` | `OAK_CAPTURE_CONTENT` |
| `content_max_chars` | `12000` | `OAK_CONTENT_MAX_CHARS` |
| `exporter` | `grpc` | `OTEL_EXPORTER_OTLP_PROTOCOL` |
| `endpoint` | — | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| pricing | bundled | `OAK_PRICING_FILE` |

## Guarantees

- `ParentBased(ALWAYS_ON)` sampling; traceparent on every hop.
- **No content capture** by default; `gen_ai.*` keys are vendor-neutral (never namespaced).
- Core install is web-dependency-free; fastapi/httpx/mcp live only in extras.

## Reference app

See [`examples/research_mesh/`](examples/research_mesh/) — a planner->researcher->writer->
critic->router pipeline with real web search, real output->input threading, opt-in capture, and
the self-defending loop/breaker beat, plus a one-command SigNoz + agents `compose.yaml`.

**Reproducible SigNoz deploy (Foundry):** the example ships a committed
[`casting.yaml`](examples/research_mesh/signoz/casting.yaml) +
[`casting.yaml.lock`](examples/research_mesh/signoz/casting.yaml.lock) — reproduce with
`foundryctl cast -f examples/research_mesh/signoz/casting.yaml`. The example `compose.yaml`
includes the same Foundry-rendered stack.

Apache-2.0.
