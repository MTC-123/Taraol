# taraol

**Drop-in OpenTelemetry for multi-agent systems.** Any Python agent gets gen_ai-semconv spans,
cross-process `traceparent`, cost rollup, a live SigNoz topology, and an analysis + enforcement
toolkit (runaway-loop detection, injection blast-radius, per-edge breaker, bad-output provenance)
— in ~3 lines. Framework-neutral, **private by default**.

> Built for the "Agents of SigNoz" hackathon. `demos/research_mesh/` is a full reference app
> (5 agents, real web search, real LLM) built entirely on this library.

![taraol Service Map in SigNoz — planner → researcher → writer → critic → router, reconstructed from cross-process traceparent](docs/service-map.png)

## Install

```sh
pip install taraol            # core: OTel SDK + gRPC OTLP + pyyaml
pip install "taraol[all]"     # + a2a, detection, mcp, search, llm, http extras
```

## Backend

The kit is the OTLP **client**. Point it at any SigNoz — Cloud/existing collector via
`OTEL_EXPORTER_OTLP_ENDPOINT`, or boot one locally:

```sh
taraol signoz up      # local SigNoz (UI :8080, OTLP :4317); `signoz down` to wipe
```

## Quickstart

Drop three decorators on the functions you already have:

```python
from taraol import instrument, agent, chat, tool

instrument("planner")                         # OTel wired, zero config

@tool                                         # execute_tool span
def search(query): ...

@chat("gemini-2.5-flash")                     # chat span; tokens + cost auto-extracted
def think(prompt):
    return client.models.generate_content(model="gemini-2.5-flash", contents=prompt)

@agent(name="planner")                        # invoke_agent span around the step
def plan(task):
    return think(search(task)).text
```

Return the raw SDK response from a `@chat` function and usage/cost are read off it
automatically (google-genai, OpenAI-compatible, Anthropic shapes); `record_chat(...)` remains
for streaming/custom cases.

`instrument()` installs one `ParentBased(ALWAYS_ON)` provider, a batching OTLP exporter, W3C
trace-context + baggage propagation, and the bundled price table. Agents that propagate
`traceparent` render as the live **Service Map** above — no custom UI. Need streaming / async /
fine control? The context managers do the same:
`with kit.agent("planner", conversation_id), kit.chat("gemini-2.5-flash") as c: c.record(...)`.

## Opt-in step inspection

Off by default — **no prompt/output/tool text is ever captured**. Turn it on with
`OAK_CAPTURE_CONTENT=on`:

```python
with kit.chat("gemini-2.5-flash") as c:
    c.record(input_tokens=n_in, output_tokens=n_out)
    c.record_content(prompt=prompt, completion=output)          # gen_ai.input/output.messages

taraol explain <trace-id> --replay                      # per-agent input -> output -> tools
```

Captured text is truncated (default 12k/field) with an `agentmesh.content.truncated` marker.
With the `@chat` decorator no call is needed at all — once opted in, prompt + completion are
captured off the function argument and returned response automatically.

## AgentLab — compare AI agent variants with one function call

Which prompt, model, or workflow is cheaper, faster, and *safer to run*? AgentLab tags every span
+ signal with `experiment.id` / `variant` / `run_id`, fires the same workload once per variant, and
compares them on real telemetry — cost, latency, tokens, **loops, breaker trips, failures** — not
answer quality. **SigNoz is the dashboard.**

```
variant A ─┐                           cost · latency · tokens
variant B ─┼─ AgentLab run ──> SigNoz ── loops · breakers · fails ──> pick the safest
variant C ─┘  (one run_id)             dashboard + summary CLI
```

```python
from taraol import Experiment

(Experiment("converge-vs-runaway", author="Fraol")
    .variant("baseline", loop_mode="off")
    .variant("runaway",  loop_mode="storm")
    .run(workload))                                             
```

One `.run()` = one shared `run_id` (Experiment → Run → Variant → Trace); a variant that raises is
recorded `failed` and the run continues. Compare in the terminal (SigNoz Query API if
`SIGNOZ_API_KEY`, else ClickHouse fallback) or import the **experiment-comparison** dashboard:

```sh
taraol experiment summary converge-vs-runaway    # per-variant table + health
taraol experiment diff <run1> <run2>             # cost/latency/loops deltas
```

```
variant       cost$   tokens  loops  breakers  fails  health
baseline      0.0120    1200      0         0      0    99.6
runaway       0.0480    4800      6         2      1     9.0
Highest Operational Health: baseline
```

`HealthScore` is pluggable (`100 − 10·loops − 5·breaker − 0.2·latency_s − 0.1·cost − 20·fails`,
weights overridable) and "highest health" is a factual read, not a universal winner. Runnable
baseline-vs-runaway: [`demos/research_mesh/experiment.py`](demos/research_mesh/experiment.py).

## Analysis + enforcement toolkit

```python
from taraol import find_cycles, find_directed_cycles, origin_of_bad_output
from taraol.breaker import get_registry, edge_key

find_cycles(trace_spans)                      # per-trace loops
origin_of_bad_output(spans, kit.names)        # who produced bad output, who consumed it
get_registry().allow(edge_key("a", "b"))      # per-edge circuit breaker
kit.mark_injection("jailbreak")               # taint active span; spreads via baggage
```

The `[detection]` extra ships a **watcher** (flags runaway loops / budget breaches / injection
blast-radius / unhealthy edges) and a **controller** (alert webhook -> pause agent or trip a breaker
-> trace-correlated audit). Cross-process context: `inject_into(headers)` / `extract_from(headers)`.
Bundled dashboards + alert Terraform: `taraol dump-dashboards ./out`.

## Configuration

Zero-config defaults; override via `instrument(...)`, `Settings`, or env.

| Setting | Default | Env |
|---|---|---|
| `attr_namespace` | `agentmesh` | `OAK_ATTR_NAMESPACE` |
| `capture_content` | `False` | `OAK_CAPTURE_CONTENT` |
| `content_max_chars` | `12000` | `OAK_CONTENT_MAX_CHARS` |
| `endpoint` | — | `OTEL_EXPORTER_OTLP_ENDPOINT` |

**Guarantees:** `ParentBased(ALWAYS_ON)` sampling; no content capture by default; `gen_ai.*` keys
never namespaced; core install is web-dependency-free (fastapi/httpx/mcp live in extras only).

## Reference app

[`demos/research_mesh/`](demos/research_mesh/) — a planner->researcher->writer->critic->router
pipeline with real search, output->input threading, opt-in capture, and the self-defending
loop/breaker beat, plus a one-command SigNoz + agents `compose.yaml`. Reproducible Foundry deploy:
committed [`casting.yaml`](demos/research_mesh/signoz/casting.yaml) +
[`.lock`](demos/research_mesh/signoz/casting.yaml.lock) →
`foundryctl cast -f demos/research_mesh/signoz/casting.yaml`.

Apache-2.0.
