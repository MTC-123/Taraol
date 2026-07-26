# trip-planner — a real-life agent team on taraol

`scout -> itinerary-writer -> budget-critic -> booker`, one process, real Gemini, and the
**decorator tier** of the taraol API (`@agent` / `@chat` / `@tool` — tokens, cost, and
opted-in content read straight off the returned SDK response).

The AgentLab experiment books the **same Tokyo trip under three conditions**:

| variant | what happens | the taraol beat |
|---|---|---|
| `comfort` | $2500 budget — critic approves, booker confirms | clean pass, cost + latency baseline |
| `shoestring` | $800 budget — the trip *physically can't fit* (~$1630 fixed costs); the agents loop revising instead of admitting it | writer↔critic revision loop → per-edge **circuit breaker trips OPEN** → cut, recorded `failed` |
| `poisoned` | scraped attraction reviews carry a prompt injection | **guardrail** flags it → span **tainted** for provenance → trip refused |

## Run

```sh
# needs a SigNoz (taraol signoz up) and GEMINI_API_KEY + OTEL_EXPORTER_OTLP_ENDPOINT in .env
uv run python demos/trip_planner/app.py

# then compare the variants
SIGNOZ_CLICKHOUSE_URL=http://localhost:8123 taraol experiment summary tokyo-trip
```

The demo ladder: **this** (4 agents, one process, decorator tier, self-defense) →
[`research_mesh/`](../research_mesh/) (5 containers, cross-process traces, Service Map, watcher
loop detection, alert → controller enforcement).
