# Loop watcher

`loop-watcher` is a read-only SigNoz consumer. It does not import, pause, or otherwise control
the demo agents; PLAN 06 owns enforcement.

Each poll has two independent paths:

1. A cheap Query Builder v5 query finds repeated `a2a.call` edges per trace in the recent window.
   The watcher fetches each suspicious trace and confirms that the same edge participates in a
   service ancestry cycle. Parallel sibling calls are not a cycle.
2. It finds conversations active in the recent window, then sums only direct `chat` span costs for
   each conversation across the budget lookback. This deliberately excludes recursively aggregated
   hop costs.

Signals are structured OTLP logs from `loop-watcher`, correlated by trace ID, plus low-cardinality
`agentmesh.loops.detected` and `agentmesh.budget.breaches` counters. Deduplication is in memory;
restarting the watcher resets its cooldown state.

Set `SIGNOZ_URL` and `SIGNOZ_API_KEY` for the SigNoz API path. For a self-hosted local stack,
set `SIGNOZ_CLICKHOUSE_URL` instead to use its private, read-only ClickHouse HTTP endpoint;
never expose that endpoint publicly. Compose selects this local fallback automatically and exports
the watcher's logs and metrics through `ingester:4317`.
