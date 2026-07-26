# Taraol

> **Observe, debug, defend, and improve AI agents with SigNoz.**

Taraol is an **OpenTelemetry-native observability framework for AI agents** that turns your
Python agents into observable, experimentable, and self-defending systems.

With only **two decorators**, Taraol provides:

- 🔍 End-to-end distributed tracing
- 🗺️ Live Service Maps in SigNoz
- 💰 Automatic LLM token & cost tracking
- 🧠 Prompt and response replay
- 🧪 AgentLab — operational experiments
- 🔄 Runaway loop detection
- 🚧 Per-edge circuit breakers
- 🛡️ Prompt-injection taint tracking
- 📍 Bad-output provenance
- ☁️ Vendor-neutral OpenTelemetry instrumentation

Unlike framework-specific solutions, Taraol works with **any Python AI agent** while remaining
completely vendor-neutral through **OpenTelemetry**.

Built for the **Agents of SigNoz Hackathon**. Every number and screenshot in this README comes
from a real, live-verified run.

![Taraol Service Map in SigNoz — planner → researcher → writer → critic → router, five services reconstructed from cross-process traceparent](docs/service-map.png)

---

## Why Taraol?

Modern AI applications are no longer a single prompt.

Today's systems are built from **multiple collaborating agents**.

```
            User
              │
              ▼
         Planner Agent
              │
      ┌───────┴────────┐
      ▼                ▼
  Researcher        Web Search
      │
      ▼
    Writer
      │
      ▼
    Critic
      │
      ▼
  Final Answer
```

As soon as an application becomes a team of agents, completely new operational problems appear:

- Which agent failed?
- Which prompt caused the failure?
- Why did costs suddenly increase?
- Why are two agents talking forever?
- Which downstream agents consumed poisoned output?
- Which workflow is actually better in production?

Traditional observability platforms answer infrastructure questions.

LLM evaluation platforms answer quality questions.

**Neither explains how the entire agent system behaves.**

That is the problem Taraol solves — in four verbs:

| | |
|---|---|
| **Observe** | every agent, tool, model call, token, and cost becomes an OpenTelemetry trace in SigNoz |
| **Debug** | replay any conversation — prompts, completions, tool I/O — from telemetry |
| **Defend** | detect runaway loops, injection spread, and budget burn; cut them with circuit breakers |
| **Improve** | AgentLab compares agent designs on real operational telemetry and tells you which to ship |

---

## Architecture

```
                        ┌──────────────────────────────┐
                        │       Your AI Agents         │
                        │  planner · researcher ·      │
                        │  writer · critic · router    │
                        └──────────────┬───────────────┘
                                       │
                          @agent / @chat / @tool
                                       │
                                       ▼
                            Taraol instrumentation
                                       │
                            OpenTelemetry SDK + OTLP
                                       │
                                       ▼
                          ┌─────────────────────────┐
                          │         SigNoz          │
                          │  traces · logs · metrics│
                          │  service map · alerts   │
                          │  dashboards             │
                          └────────────┬────────────┘
                                       │
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
                 Watcher service               Experiment CLI
              (loop / edge / budget /        (summary · diff ·
               injection detection)              replay)
                        │
                        ▼
                Controller service
          pause agent · break edge · audit
```

Each layer has a single responsibility, and every layer speaks standard OpenTelemetry —
no proprietary protocol anywhere in the stack.

---

## Installation

```bash
pip install taraol            # core: OTel SDK + gRPC OTLP + pyyaml
pip install "taraol[all]"     # + a2a, detection, mcp, search, llm, http extras
```

## One command to SigNoz

Taraol uses **SigNoz** as its observability backend. If you don't have one running:

```bash
taraol signoz up      # boots a complete local SigNoz (UI :8080, OTLP :4317)
taraol signoz down    # stop + wipe
```

Or point at **SigNoz Cloud** — no code changes:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://ingest.<region>.signoz.cloud:443
OTEL_EXPORTER_OTLP_HEADERS=signoz-ingestion-key=<YOUR_KEY>
```

### Reproducible deployments with Foundry

The bundled SigNoz is not a hand-rolled compose file — it is a committed **Foundry**
deployment (`casting.yaml` + `casting.yaml.lock`), shipped inside the wheel and in the repo:

```bash
foundryctl cast -f demos/research_mesh/signoz/casting.yaml
```

Anyone — including hackathon judges — reproduces the exact same environment. No undocumented
Docker commands. No missing services.

---

## Your first instrumented agent

Without Taraol:

```python
response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
```

No tracing. No costs. No observability.

Now add Taraol:

```python
from taraol import instrument, agent, chat

instrument("assistant")

@chat("gemini-2.5-flash")
def think(prompt):
    return client.models.generate_content(model="gemini-2.5-flash", contents=prompt)

@agent(name="assistant")
def answer(question):
    return think(question).text
```

That's the entire instrumentation. No SDK wrappers. No monkey patching. No framework lock-in.

### What happens automatically

The moment those decorators run, every invocation emits:

✅ distributed traces (gen_ai semantic conventions)
✅ token counts — read straight off the returned SDK response
✅ LLM cost estimates (bundled price table)
✅ conversation ids and agent hierarchy
✅ the live Service Map

Automatic token/cost extraction currently understands **google-genai, OpenAI-compatible,
Anthropic, and flat result shapes**; anything else records explicitly with one
`record_chat(...)` call. Taraol never owns your application — you keep whatever SDK or
framework you already use.

### Privacy first

Content capture is **disabled by default** — no prompts, completions, or tool text are ever
stored. Opt in explicitly:

```python
instrument("assistant", capture_content=True)
```

and chat spans additionally record prompts, completions, and tool I/O using the standard
`gen_ai.*` semantic conventions (truncated, with a marker). Experiment knob values follow the
same rule — off by default.

### Replay any conversation

```bash
taraol explain <trace-id> --replay
```

```
[2] researcher   (113->21 tok, $0.0001)
    input:  You are the researcher agent (step 1). ...
    output: Tracing matters because it delivers crucial end-to-end visibility...
    tool search_sources: -> [3 results]
```

The same chain inside SigNoz — flame graph, waterfall across five services, and the captured
prompt on the selected span:

![A research-mesh trace in SigNoz: flame graph + waterfall across five services, gen_ai.input/output.messages visible on the selected chat span](docs/mesh-trace.png)

---

# AgentLab — operational experiments

Observability tells you **what happened**.

AgentLab tells you **which design should go to production**.

Most evaluation tools compare answer quality. AgentLab compares **operational behavior** —
what actually matters in production:

- cost
- latency
- token usage
- failures
- runaway loops
- circuit-breaker trips

using real telemetry collected by SigNoz.

## One function call

```python
from taraol import Experiment

result = (
    Experiment("docs-assistant", description="prompt comparison", author="Fraol")
    .compare("terse",   prompt="Explain OpenTelemetry in exactly one sentence.")
    .compare("verbose", prompt="Explain OpenTelemetry in three detailed paragraphs.")
    .compare("broken")                    # a failing variant is recorded, not fatal
    .run(answer)                          # answer(ctx) runs once per variant
)
```

Every span generated during a variant automatically carries `experiment.id`,
`experiment.variant`, and `experiment.run_id`.

## Experiment hierarchy

```
Experiment
    │
    ├── Run (one .run() = one shared run_id)
    │      ├── Variant A ── Trace
    │      ├── Variant B ── Trace
    │      └── Variant C ── Trace
    │
    └── Future runs — never mixed with today's
```

Repeated executions stay isolated: compare today's deployment against yesterday's by run id,
or widen the SigNoz time range to watch regression across runs.

## Compare more than prompts

A variant is just configuration — anything that changes your agent can become one:

```python
.compare("gpt4",    model="gpt-4o")
.compare("gemini",  model="gemini-2.5-flash")

.compare("baseline", loop_mode="off")
.compare("runaway",  loop_mode="storm")

.compare("comfort",    budget=2500)
.compare("shoestring", budget=800)
```

## Why operational experiments?

A real run from this repo — same trip-planning workload, three conditions:

| variant | cost $ | tokens | avg ms | fails | what happened |
|---|---|---|---|---|---|
| comfort | 0.0008 | 318 | 14,312 | 0 | critic approved, trip booked |
| shoestring | 0.0028 | 1,012 | 48,766 | 1 | budget can't fit → agents looped → **breaker cut it** |
| poisoned | 0.0000 | 0 | 16 | 1 | **guardrail blocked** an injected prompt instantly |

Both prompt-evaluation tools and human review would call the shoestring itinerary "fine."
Telemetry shows it burned **3.5× the cost** producing nothing. AgentLab makes the deploy
decision evidence-based.

## SigNoz is the dashboard

AgentLab builds **no custom UI**. Because every span carries the experiment attributes,
SigNoz becomes the experiment dashboard — and Taraol ships one ready-made
(`taraol dump-dashboards`, then import):

![AgentLab experiment-comparison dashboard in SigNoz — P95 latency, direct LLM cost, and output tokens split by experiment.variant](docs/agentlab-dashboard.png)

## Experiment summary CLI

```bash
taraol experiment summary converge-vs-runaway --run <run_id>
taraol experiment diff <run1> <run2>
```

A real run on the distributed mesh (five services, live Gemini):

```
variant       cost$   tokens  agents   avg ms  loops  breakers  fails  health
baseline     0.0116     4127       5    42460      0         0      0    91.5
runaway      0.0266     9457       5   130972      1         1      0    58.8

Highest Operational Health: baseline
```

The runaway variant cost 2.3×, ran 3× longer — and the **loops** and **breakers** columns come
from the watcher detecting the storm *in telemetry*. The `HealthScore` is pluggable
(`100 − 10·loops − 5·breaker − 0.2·latency_s − 0.1·cost − 20·fails`), and "highest health" is a
factual read, not a universal winner — tune the weights to what you optimize.

---

# Self-defending agent mesh

Observability tells you what went wrong. Production systems also need to decide
**what should happen next**.

```
   Agents ──> OpenTelemetry ──> SigNoz ──> Watcher ──> Controller
                                              │            │
                                       loop_detected   pause agent
                                       edge_unhealthy  break edge
                                       budget_exceeded audit event
```

### Runaway loop detection

The most common multi-agent failure: two agents revising each other forever.

```
Writer ──> Critic ──> Writer ──> Critic ──> Writer ──> ...
```

Every iteration is a real LLM bill. And in a distributed system, **no single agent can see
the loop** — the planner has no idea the writer and critic are ping-ponging. The only place
the pattern exists is the telemetry.

The Taraol **watcher** continuously analyzes traces in SigNoz and emits a trace-correlated
`loop_detected` signal when a conversation stops making progress — carrying the experiment
variant that caused it.

### Per-edge circuit breakers

Sometimes only **one communication path** is unhealthy.

```
Planner ────────► Writer ──X──► Critic
Researcher ─────► Writer            (only this edge is cut)
```

Instead of stopping the whole workflow, Taraol trips a breaker on the single bad edge
(closed → open → half-open), minimizing blast radius while the rest keeps working.

### Injection taint tracking

Malicious prompts spread: if the researcher consumes a poisoned document, every downstream
agent may inherit the attack. Taraol's guardrail scanner flags suspicious content, marks the
span, and propagates the taint via OpenTelemetry baggage — so instead of asking *"was this
agent attacked?"* you ask *"which agents consumed poisoned information?"* and read the blast
radius off SigNoz.

### Bad-output provenance

When a wrong answer reaches a user, `origin_of_bad_output` reconstructs from telemetry who
**produced** the bad content and who merely **consumed** it — across all agents.

### Alert-driven enforcement

Detection closes into action through SigNoz itself:

```
loop_detected ──> SigNoz alert rule ──> webhook ──> Controller ──> agent paused
                                                          │
                                                          └──> audit event (trace-correlated)
```

Nothing happens silently. Every enforcement action is itself telemetry.

### Operational signals

| signal | meaning |
|---|---|
| `loop_detected` | a conversation is looping without progress (repeated state / iteration cap) |
| `edge_unhealthy` | one agent→agent edge is over its hop budget (carries `breaker_reason`) |
| `budget_exceeded` | a conversation blew its cost budget |
| `injection_detected` | taint found, with origin + blast radius |
| `xconv_loop_detected` | a loop spread across separate conversations |
| `agent_paused` / `edge_broken` | controller audit events after enforcement |

All are OpenTelemetry log records — searchable in SigNoz next to the traces they point at.

---

## The demos (a ladder)

| demo | scale | shows |
|---|---|---|
| [`main.py`](main.py) | 1 agent, 1 process | quickstart + the terse-vs-verbose prompt experiment |
| [`main_2.py`](main_2.py) | 3 agents, 1 process | revision loop → breaker; guardrail catches injection |
| [`demos/trip_planner/`](demos/trip_planner/) | 4 agents, 1 process | a real-life app on the decorator tier |
| [`demos/research_mesh/`](demos/research_mesh/) | **5 services, containers** | cross-process traces, Service Map, watcher detection, alert → controller enforcement, Foundry deploy |

```bash
# the distributed story, one command:
docker compose -f demos/research_mesh/compose.yaml up -d --build
docker exec research-mesh-planner-1 python -m research_mesh.experiment
```

---

## Why Taraol vs the alternatives

| capability | Taraol | typical LLM-eval / framework tracers |
|---|---|---|
| OpenTelemetry-native (W3C traceparent, gen_ai semconv) | ✅ | varies — often proprietary SaaS |
| Works with any Python code, no framework ownership | ✅ | usually tied to one framework |
| Distributed multi-service agent mesh | ✅ | mostly single-process traces |
| Live Service Map | ✅ (SigNoz) | ❌ |
| Operational experiments (cost/loops/breakers per variant) | ✅ AgentLab | ❌ — they compare answer quality |
| Loop detection **from telemetry** | ✅ | ❌ |
| Per-edge circuit breakers | ✅ | ❌ |
| Injection taint propagation | ✅ | ❌ |
| Alert → automatic enforcement | ✅ | ❌ |
| Reproducible backend deploy (Foundry) | ✅ | n/a |

Evaluation tools answer *"which answer is better?"*
Taraol answers *"which workflow is cheaper, more stable, and safer — and should I deploy it?"*

---

## Configuration

Zero-config defaults; override via `instrument(...)`, `Settings`, or env.

| setting | default | env |
|---|---|---|
| content capture | off | `OAK_CAPTURE_CONTENT` |
| attribute namespace | `agentmesh` | `OAK_ATTR_NAMESPACE` |
| OTLP endpoint | — | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| A2A hop timeout | 10 s | `OAK_A2A_TIMEOUT_SEC` |
| experiment tags | off | `OAK_EXPERIMENT_ID / _VARIANT / _RUN_ID` |

**Guarantees:** `ParentBased(ALWAYS_ON)` sampling · no content capture by default ·
`gen_ai.*` keys are standard semconv, never namespaced · core install is web-dependency-free.

---

Apache-2.0.
