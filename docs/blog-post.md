---
title: "Two decorators, and your agent team defends itself"
published: false
description: "Taraol turns any Python agent into OpenTelemetry telemetry in three lines — then reads that telemetry back to draw the topology, replay the conversation, cut runaway loops with circuit breakers, and tell you which design to ship. All inside SigNoz, with no custom UI."
tags: opentelemetry, observability, ai, python
cover_image: https://raw.githubusercontent.com/MTC-123/Taraol/main/docs/defend-beat.gif
canonical_url:
---

SigNoz's framing for this hackathon is *"if you can't observe your AI agents, you don't own
them."* I want to push on it: observing is table stakes. The interesting question is what
your system can **do** with what it observed, while it's still running.

Here's a run from the distributed demo — the same workload, two designs:

```
variant       cost$   tokens  agents   avg ms  loops  breakers  fails  health
baseline     0.0116     4127       5    42460      0         0      0    91.5
runaway      0.0266     9457       5   130972      1         1      0    58.8

Highest Operational Health: baseline
```

Two prompts. Both produce a fine answer. One costs 2.3× more, runs 3× longer, spins a
runaway loop, and trips a circuit breaker on the way. **No prompt-eval tool will ever tell
you that** — it's not a quality difference, it's an operational one, and it only exists in
telemetry.

That's Taraol: an OpenTelemetry-native framework for AI agents that turns instrumentation
into four verbs — **Observe, Debug, Defend, Improve** — with SigNoz as the entire UI.

![The same workload, two designs](https://raw.githubusercontent.com/MTC-123/Taraol/main/docs/agentlab-compare.gif)

---

## The failure modes are structural, not accidental

Modern AI apps aren't a prompt anymore. They're teams. And teams fail in ways a single
service doesn't:

- Two agents **revise each other forever**. Every iteration is individually valid, every
  call returns 200, and every loop is a real LLM bill.
- A poisoned document **injects instructions** that spread silently to every downstream
  agent that reads the output.
- In a distributed system, **no single agent can see either problem.** The planner has no
  idea the writer and critic are ping-ponging.

That last point is the load-bearing one. The pathology doesn't exist inside any one
process — it exists in the *shape of the traffic between them*. So the only place you can
detect it is the telemetry.

Which is convenient, because if detection reads telemetry rather than application code, it
works regardless of framework, language, or who wrote which agent.

## Observe: three lines, and you keep your code

The integration is deliberately boring. `instrument()` once per process — it wires a
`ParentBased(ALWAYS_ON)` provider, a batching OTLP exporter, W3C trace context + baggage,
and the price table. Then decorators wrap functions you already have:

```python
from taraol import instrument, agent, chat, tool

instrument("assistant")


@tool  # execute_tool span
def search(query): ...


@chat("gemini-2.5-flash")  # chat span (gen_ai semconv) + cost rollup
def think(prompt):
    return client.models.generate_content(model="gemini-2.5-flash", contents=prompt)


@agent(name="assistant")  # invoke_agent span around the step
def answer(question):
    return think(search(question)).text
```

The function bodies stay your normal SDK calls. No wrappers, no monkey patching, no
framework taking ownership of your app. Taraol instruments **OpenTelemetry**, not a
framework — so the same telemetry goes to SigNoz today and any other OTel backend tomorrow.

Return the raw SDK response from a `@chat` function and usage is read straight off it —
google-genai, OpenAI-compatible, Anthropic, and flat result shapes are all duck-typed. No
manual token counting.

**Content capture is off by default.** No prompt, completion, or tool text leaves your
process unless you explicitly opt in. A test asserts `gen_ai.input.messages` is absent on
the default path — the privacy claim is enforced, not documented.

### The map draws itself

Here's the part I find genuinely delightful, and the reason this is built on SigNoz rather
than a bespoke dashboard.

**There is no topology renderer in this project.** Not one line.

SigNoz's Service Map is derived from two things ordinary distributed tracing already gives
you: span parent/child relationships and `service.name`. Make each agent its own service,
propagate trace context on every hop, and the agent mesh *is* a service map. It renders for
free, reflects real production topology, and changes as traffic changes.

![The Taraol Service Map in SigNoz](https://raw.githubusercontent.com/MTC-123/Taraol/main/docs/service-map.png)

![How the mesh assembles, then closes into a cycle](https://raw.githubusercontent.com/MTC-123/Taraol/main/docs/mesh-topology.gif)

*(Diagram — the topology forming, then the writer ↔ critic revision loop closing it.)*

### The one setting that will bite you

```python
sampler = ParentBased(ALWAYS_ON)
```

If each agent samples independently, agent three drops a trace that agents one and two
kept. You get a *shredded* mesh: edges that flicker, cycles that never close, cost that
doesn't add up. `ParentBased` means a child never re-decides — it inherits the root's
decision. Get this wrong and every feature below silently degrades.

![One trace id across five processes](https://raw.githubusercontent.com/MTC-123/Taraol/main/docs/traceparent-hop.gif)

### Cost, without double-counting

This one took a bug to get right. Cost splits into two attributes that mean different
things:

- **`agentmesh.cost.direct_usd`** — one agent's own chat call. Additive across a
  conversation; sum these for the true total.
- **`agentmesh.cost.downstream_usd`** — on a hop span, the cost of the callee's *entire
  subtree*. This is per-delegation attribution — which path drives spend — and is
  explicitly **not** additive across edges.

Sum both and you double-count the whole conversation. The bundled dashboards use
`direct_usd` for per-agent and per-conversation cost, `downstream_usd` for the per-edge
view.

## Debug: replay the conversation from telemetry

When something goes wrong you don't want a trace ID, you want the transcript:

```bash
taraol explain <trace-id> --replay
```
```
[2] researcher   (113->21 tok, $0.0001)
    input:  You are the researcher agent (step 1). ...
    output: Tracing matters because it delivers crucial end-to-end visibility...
    tool search_sources: -> [3 results]
```

That's reconstructed from trace rows, not from an application-side log the app had to
remember to write. The wire format stays standard `gen_ai.*` message lists, so any
OTel-aware tool can read it — the renderer just decodes it to something human.

![A research-mesh trace in SigNoz](https://raw.githubusercontent.com/MTC-123/Taraol/main/docs/mesh-trace.png)

## Defend: detection that does something

This is the beat I care about most. Detection that only produces a notification still needs
a human awake at 3am.

```
   Agents ──> OpenTelemetry ──> SigNoz ──> Watcher ──> Controller
                                              │            │
                                       loop_detected   pause agent
                                       edge_unhealthy  break edge
```

![Loop detected, edge cut, agent paused](https://raw.githubusercontent.com/MTC-123/Taraol/main/docs/defend-beat.gif)

**Runaway loops.** The watcher looks for repeated communication cycles that make *no
progress* — distinguished by a repeated state hash or a breached iteration cap. That
qualifier matters: an intentional generator/critic loop is a legitimate design, and a
detector that flags it is a detector you'll turn off. Cross-conversation loops get their own
signal (`xconv_loop_detected`) for an agent ping-ponging across separate traces.

**Per-edge circuit breakers.** Sometimes the agent is fine and only one path is bad:

```
Planner ────────► Writer ──X──► Critic
Researcher ─────► Writer            (only this edge is cut)
```

An independent breaker per edge (closed → open → half-open) short-circuits before dispatch,
so a poisoned or runaway hop stops flowing while the rest of the workflow keeps running.
Blast radius stays minimal instead of the whole agent going dark.

**Injection taint.** Agents exchange natural language, so a malicious prompt propagates like
a contagion. Scan an input, mark the span, and the taint spreads downstream automatically
via OTel baggage:

```python
verdict = scan(fetched_docs, INPUT)
if verdict.flagged:
    kit.mark_injection(verdict.category)  # spreads via baggage
```

The question changes from *"was this agent attacked?"* to *"which agents consumed poisoned
information?"* — and you read the blast radius off SigNoz.

**Enforcement closes the loop.** A SigNoz alert fires on the signal, a webhook hits the
controller, and the controller pauses the agent or trips the breaker — then records the
action as its own telemetry (`agent_paused`, `edge_broken`). **Nothing happens silently.**
Enforcement is observable, which is the only version of automated enforcement I'd actually
run in production.

Every signal is an ordinary OpenTelemetry log record, searchable next to the trace it points
at:

| signal | meaning |
|---|---|
| `loop_detected` | a conversation is looping without progress |
| `edge_unhealthy` | one agent→agent edge is over its hop budget |
| `budget_exceeded` | a conversation blew its cost budget |
| `injection_detected` | taint found, with origin + blast radius |
| `xconv_loop_detected` | a loop spread across separate conversations |
| `agent_paused` / `edge_broken` | controller audit events after enforcement |

No separate monitoring system. No custom database. It's all SigNoz.

## Improve: which design should I actually deploy?

Observability tells you what happened. It doesn't tell you what to ship.

```python
from taraol import Experiment

(
    Experiment("docs-assistant", author="Fraol")
    .compare("terse", prompt="Explain OpenTelemetry in exactly one sentence.")
    .compare("verbose", prompt="Explain OpenTelemetry in three detailed paragraphs.")
    .compare("broken")  # a failing variant is recorded, not fatal
    .run(answer)
)
```

Every span emitted during a variant carries `experiment.id`, `experiment.variant`, and
`experiment.run_id` — **including cross-process hop spans**. So SigNoz becomes the
experiment dashboard, with no new UI and no separate store.

![The AgentLab comparison dashboard in SigNoz](https://raw.githubusercontent.com/MTC-123/Taraol/main/docs/agentlab-dashboard.png)

Which produces the table at the top of this post. The `loops` and `breakers` columns aren't
instrumented by the experiment — they come from the **watcher detecting the storm in
telemetry**, with the signals carrying the variant that caused them. Defend and Improve are
the same data read two ways.

The health score is deliberately transparent and overridable:

```
health = 100 − 10·loops − 5·breaker_trips − 0.2·latency_s − 0.1·cost_usd − 20·failures
```

"Highest Operational Health" is a factual read against weights *you* set, not a universal
winner. One team optimises cost, another latency, another stability. A tool that hard-codes
that tradeoff is lying to somebody.

Small design detail I'd defend: a variant that raises is recorded `status=failed` and the
run continues. An experiment runner that aborts on one failure is useless precisely when
you need it.

## Try it

```bash
pip install "taraol[all]"
taraol signoz up          # local SigNoz, or point at SigNoz Cloud
```

Two demos, deliberately at different scales:

```bash
# 4 agents, one process, real Gemini — decorators, an experiment,
# a revision loop that trips a breaker, a guardrail catching an injection
uv run python demos/trip_planner/app.py

# 5 services in containers — cross-process traces, Service Map,
# watcher detection, alert → controller enforcement
docker compose -f demos/research_mesh/compose.yaml up -d --build
docker exec research-mesh-planner-1 python -m research_mesh.experiment
```

## Honest edges

- **Replay requires opting into content capture.** That's the right default, but it means
  the transcript isn't there retroactively for an incident you didn't anticipate.
- **Detection analyses telemetry, so it isn't instantaneous.** It's bounded by ingest and
  analysis, not by an in-process hook. The tradeoff buys framework independence.
- **AgentLab's summary needs the `[detection]` extra** and a few seconds for batched
  telemetry to land before the numbers are complete.
- **The health weights are a heuristic.** They're a starting point you're expected to tune,
  not a benchmark.
- **Cost accuracy is bounded by the price table.** Update it when providers change pricing.

## The takeaway

If you run more than one agent, the useful question isn't "what did this agent do." It's
**"what is the shape of the traffic between them, what is that shape costing me, and can
the system cut it before I wake up."**

You can answer all three today without a proprietary SDK, by doing two boring things well:
give every agent its own `service.name`, and propagate `traceparent` on every hop. SigNoz
draws the rest — and once the telemetry is good enough to draw the map, it's good enough to
defend it.

Code: **[github.com/MTC-123/Taraol](https://github.com/MTC-123/Taraol)** — Apache-2.0,
framework-neutral, vendor-neutral, content-free by default.

Built on [SigNoz](https://signoz.io/) and [OpenTelemetry](https://opentelemetry.io/).

*Submitted to the Agents of SigNoz hackathon — Track 01, AI & Agent Observability.*
