# Observability — instrumentation, tracing, cost, replay

The core of Taraol: turn any Python agent into full OpenTelemetry telemetry with two
decorators, then read it — traces, tokens, cost, topology, and (opt-in) the actual
conversation — inside SigNoz.

- [Instrument with decorators](#instrument-with-decorators)
- [Automatic token & cost extraction](#automatic-token--cost-extraction)
- [Cost model: direct vs downstream](#cost-model-direct-vs-downstream)
- [Distributed tracing across processes](#distributed-tracing-across-processes)
- [Live Service Map](#live-service-map)
- [Content capture & replay (opt-in)](#content-capture--replay-opt-in)
- [Framework neutrality](#framework-neutrality)
- [The context-manager tier](#the-context-manager-tier)

---

## Instrument with decorators

`instrument("service-name")` wires OpenTelemetry once per process: a
`ParentBased(ALWAYS_ON)` provider, a batching OTLP exporter, W3C trace-context + baggage
propagation, and the bundled price table. It's idempotent — call it once at startup.

Then three decorators wrap the functions you already have:

```python
from taraol import instrument, agent, chat, tool

instrument("assistant")

@tool                                     # execute_tool span; a str return is captured
def search(query): ...

@chat("gemini-2.5-flash")                 # chat span (gen_ai semconv) + cost rollup
def think(prompt):
    return client.models.generate_content(model="gemini-2.5-flash", contents=prompt)

@agent(name="assistant")                  # invoke_agent span around the whole step
def answer(question):
    return think(search(question)).text
```

| decorator | span | operation | captures |
|---|---|---|---|
| `@agent(name=...)` | `invoke_agent <name>` | `invoke_agent` | timing, success/failure, parent-child, experiment tags |
| `@chat(model)` | `chat <model>` | `chat` | tokens, cost, finish reason, model, provider, (opt-in) prompt/completion |
| `@tool` | `execute_tool <name>` | `execute_tool` | timing, (opt-in) arguments + result |

Each is dual-form: `@agent` and `@agent(name="planner")` both work. Nesting reflects the real
call tree, so the spans form the agent hierarchy automatically.

## Automatic token & cost extraction

Return the raw SDK response from a `@chat` function and Taraol reads usage off it — no manual
counting. It duck-types the known response shapes:

| shape | usage fields |
|---|---|
| google-genai | `usage_metadata.prompt_token_count` / `candidates_token_count` |
| OpenAI-compatible | `usage.prompt_tokens` / `completion_tokens` |
| Anthropic | `usage.input_tokens` / `output_tokens` |
| flat result objects | `input_tokens` / `output_tokens` on the result itself |

A flat `finish_reason` is picked up too. For streaming or a client Taraol doesn't recognize,
record explicitly from inside the function — an explicit call always wins over auto-extraction:

```python
from taraol import record_chat
record_chat(input_tokens=n_in, output_tokens=n_out, finish_reason="stop")
```

Cost is then computed from the bundled price table (override with `OAK_PRICING_FILE`) and
rolled onto the span as `agentmesh.cost.direct_usd`.

## Cost model: direct vs downstream

Taraol splits cost into two attributes so they never double-count:

- **`agentmesh.cost.direct_usd`** — the cost of one agent's own chat call. Summing these across
  a conversation is additive and gives the true total.
- **`agentmesh.cost.downstream_usd`** — on an A2A hop span, the cost of the callee's entire
  subtree. This is a per-delegation attribution (which path drives downstream cost), **not**
  additive across edges.

That's why the bundled dashboards use `direct_usd` for per-agent/conversation cost and
`downstream_usd` for the per-edge view.

## Distributed tracing across processes

A request keeps one trace id even when it crosses HTTP, the A2A protocol, queues, multiple
containers, or multiple machines. On send, the client injects `traceparent` + baggage; on
receive, the server extracts them and continues the same trace:

```python
from taraol import inject_into, extract_from
inject_into(headers)         # on send
ctx = extract_from(headers)  # on receive
```

The `[a2a]` extra's `A2AClient` does this automatically on every hop (and stamps the
conversation id + experiment tags), so a request that begins on one machine and finishes on
another appears as **one trace** in SigNoz.

## Live Service Map

Because every service emits spans and propagates trace context, SigNoz reconstructs the
dependency graph on its own — no configuration, no hand-drawn diagram. It reflects the real
production topology and changes as traffic changes. This is the Service Map in the README
(planner → researcher → writer → critic → router), drawn purely from traceparent.

Tip: set the `deployment.environment` resource attribute
(`OTEL_RESOURCE_ATTRIBUTES=deployment.environment=my-app`) to separate apps in SigNoz's
Environment filter.

## Content capture & replay (opt-in)

**No prompt, completion, or tool text is captured by default.** Turn it on explicitly:

```python
instrument("assistant", capture_content=True)   # or OAK_CAPTURE_CONTENT=on
```

Then chat spans record `gen_ai.input.messages` / `gen_ai.output.messages` (and
`gen_ai.system_instructions`), and tool spans record arguments/results — all under standard
`gen_ai.*` semantic conventions, truncated to `content_max_chars` (default 12k) with an
`agentmesh.content.truncated` marker. With the `@chat` decorator, capture is automatic once
opted in — the prompt comes from the function argument, the completion from the returned
response, no extra call.

Reconstruct the per-agent chain — in the terminal or from code:

```bash
taraol explain <trace-id> --replay
```
```
[2] researcher   (113->21 tok, $0.0001)
    input:  You are the researcher agent (step 1). ...
    output: Tracing matters because it delivers crucial end-to-end visibility...
    tool search_sources: -> [3 results]
```
```python
from taraol import replay
steps = replay.build_steps(spans)     # framework-neutral, from trace rows
```

The wire format stays standard JSON message lists (role + content), so any OTel-aware tool
understands it; the replay renderer decodes it to readable text.

## Framework neutrality

Taraol instruments **OpenTelemetry**, not a framework, so it never owns your application. You
keep whatever SDK or framework you already use — the decorators wrap your functions, whatever
is inside them. Because everything is emitted as standard OTLP with `gen_ai.*` conventions and
W3C trace context, the same telemetry goes to SigNoz today and any other OpenTelemetry backend
tomorrow without touching application code.

## The context-manager tier

The decorators are sugar over context managers, which stay the API for fine control —
per-request conversation ids, span handles (for taint marking / state hashes), streaming, or a
custom client:

```python
kit = instrument("planner")
with kit.agent("planner", conversation_id) as span, kit.chat("gemini-2.5-flash") as c:
    result = my_streaming_call(prompt)
    c.record(input_tokens=result.n_in, output_tokens=result.n_out)
    c.record_content(prompt=prompt, completion=result.text)   # opt-in
```

Same spans, same telemetry — pick the tier that fits. The single-process demo
(`demos/trip_planner/`) uses decorators; the distributed mesh (`demos/research_mesh/`) uses
decorators for chat/tool and the CM tier for its per-request root span. See
[architecture.md](architecture.md) for the layering.
