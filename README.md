# taraol

**Drop-in OpenTelemetry for multi-agent systems.** Any Python agent gets gen_ai-semconv spans,
cross-process `traceparent`, cost rollup, a live SigNoz topology, and an analysis + enforcement
toolkit (runaway-loop detection, injection blast-radius, per-edge breaker, bad-output provenance)
— in ~3 lines. Framework-neutral, **private by default**.

> Built for the "Agents of SigNoz" hackathon. `examples/research_mesh/` is a full reference app
> (5 agents, real web search, real LLM) built entirely on this library.

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

```python
from taraol import instrument

kit = instrument("planner")                                     # OTel wired, zero config
with kit.agent("planner", conversation_id) as _a, kit.chat("gemini-2.5-flash") as c:
    c.record(input_tokens=n_in, output_tokens=n_out)            # gen_ai span + cost rollup
```

`instrument()` installs one `ParentBased(ALWAYS_ON)` provider, a batching OTLP exporter, W3C
trace-context + baggage propagation, and the bundled price table. Agents that propagate
`traceparent` render as a live **Service Map** — no custom UI. Prefer decorators? `@agent` /
`@chat` / `@tool` wrap the same context managers.

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

## AgentLab — compare operational behavior

Which prompt, model, or workflow is cheaper, faster, and *safer to run*? AgentLab tags every span
+ signal with `experiment.id` / `variant` / `run_id`, fires the same workload once per variant, and
compares them on real telemetry — cost, latency, tokens, **loops, breaker trips, failures** — not
answer quality. **SigNoz is the dashboard.**

```python
from taraol import Experiment

(Experiment("converge-vs-runaway", author="Fraol")
    .variant("baseline", config={"loop_mode": "off"})
    .variant("runaway",  config={"loop_mode": "storm"})
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
runaway       0.0480    4800      6         2      1    29.0
Highest Operational Health: baseline
```

`HealthScore` is pluggable and "highest health" is a factual read, not a universal winner. Runnable
baseline-vs-runaway: [`examples/research_mesh/experiment.py`](examples/research_mesh/experiment.py).

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

[`examples/research_mesh/`](examples/research_mesh/) — a planner->researcher->writer->critic->router
pipeline with real search, output->input threading, opt-in capture, and the self-defending
loop/breaker beat, plus a one-command SigNoz + agents `compose.yaml`. Reproducible Foundry deploy:
committed [`casting.yaml`](examples/research_mesh/signoz/casting.yaml) +
[`.lock`](examples/research_mesh/signoz/casting.yaml.lock) →
`foundryctl cast -f examples/research_mesh/signoz/casting.yaml`.

Apache-2.0.
