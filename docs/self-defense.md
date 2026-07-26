# Self-defending agent mesh

Observability tells you what went wrong. Production systems also need to decide **what should
happen next**. Taraol continuously analyzes the telemetry your agents produce and can detect,
explain, and contain failures while the system is still running.

```
   Agents ──> OpenTelemetry ──> SigNoz ──> Watcher ──> Controller
                                              │            │
                                       loop_detected   pause agent
                                       edge_unhealthy  break edge
                                       budget_exceeded audit event
```

Because detection reads telemetry — not application code — it works regardless of framework,
language, or deployment topology, even when agents are written by different teams.

## Runaway loop detection

The most common multi-agent failure is an infinite reasoning loop:

```
Writer ──> Critic ──> Writer ──> Critic ──> Writer ──> ...
```

Every iteration is valid on its own, yet the workflow never finishes — latency climbs, tokens
explode, cost burns. And in a distributed system **no single agent can see the loop**: the
planner has no idea the writer and critic are ping-ponging. The only place the pattern exists
is the telemetry.

The **watcher** analyzes completed traces in SigNoz and searches for repeated communication
cycles that make no progress — distinguished by a repeated state hash or a breached iteration
cap (an intentional generator/critic loop is *not* flagged). When it fires, it emits a
trace-correlated `loop_detected` log record carrying the reason and the experiment variant.

## Per-edge circuit breakers

Sometimes an entire agent is healthy; only one communication path is bad.

```
Planner ────────► Writer ──X──► Critic
Researcher ─────► Writer            (only this edge is cut)
```

Taraol's `EdgeBreakerRegistry` runs an independent breaker per edge (closed → open →
half-open). A hot or failing edge trips open and short-circuits before dispatch, so a runaway
or poisoned hop stops flowing while the rest of the workflow keeps running — minimizing blast
radius.

```python
from taraol.breaker import get_registry, edge_key
reg = get_registry()
if reg.allow(edge_key("writer", "critic")):
    ...        # make the call
    reg.record_success(edge_key("writer", "critic"))
```

## Injection taint tracking

Modern agents exchange natural language, so a malicious prompt can propagate through the whole
team. If the researcher consumes a poisoned document, every downstream agent may inherit the
attack.

```python
from taraol.guardrail import INPUT, scan
verdict = scan(fetched_docs, INPUT)     # jailbreak / injection patterns
if verdict.flagged:
    kit.mark_injection(verdict.category)  # taint the span; spreads via OTel baggage
```

The taint propagates to downstream hops automatically. Instead of asking *"was this agent
attacked?"* you ask *"which agents consumed poisoned information?"* and read the blast radius
off SigNoz. The `injection_detected` signal carries the origin and the comma-joined blast
radius of services reached.

## Bad-output provenance

When a wrong answer reaches a user, the question is *who actually produced it?* — across
planners, retrievers, writers, and reviewers, finding the source by hand is hard.

```python
from taraol import origin_of_bad_output
origin_of_bad_output(trace_spans, kit.names)   # who produced bad output, who consumed it
```

Provenance is reconstructed from telemetry, so the origin is found from traces rather than
manual debugging of five agents.

## Alert-driven enforcement

Detection closes into action through SigNoz itself:

```
loop_detected ──> SigNoz alert rule ──> webhook ──> Controller ──> agent paused
                                                          │
                                                          └──> audit event (trace-correlated)
```

The **controller** receives the alert webhook and pauses the runaway agent or trips the edge
breaker, recording every action as its own telemetry (`agent_paused` / `edge_broken`). Nothing
happens silently — enforcement is observable.

## Operational signals

| signal | meaning |
|---|---|
| `loop_detected` | a conversation is looping without progress (repeated state / iteration cap) |
| `edge_unhealthy` | one agent→agent edge is over its hop budget (carries `breaker_reason`) |
| `budget_exceeded` | a conversation blew its cost budget |
| `injection_detected` | taint found, with origin + blast radius |
| `xconv_loop_detected` | a loop spread across separate conversations |
| `agent_paused` / `edge_broken` | controller audit events after enforcement |

All are OpenTelemetry log records, searchable in SigNoz next to the traces they point at — no
separate monitoring system required.

## Running it

The `[detection]` extra ships the watcher and controller. See
[`demos/research_mesh/`](../demos/research_mesh/) for the full distributed setup where a
`converge-vs-runaway` experiment triggers loop detection and the breaker live.
