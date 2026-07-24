# research-mesh — reference app on otel-agent-kit

A five-agent pipeline (`planner → researcher → writer → critic → router`) built **only**
on [`otel-agent-kit`](../../packages/otel-agent-kit). It demonstrates the whole library:
distributed traces + Service Map, per-agent cost, a real web-search tool, opt-in
LangSmith-style content capture, runaway-loop detection, per-edge circuit breaker, and the
grounded `explain --replay`.

The kit does the instrumentation; this app supplies the agents, the topology
([mesh.py](mesh.py)), and the tools — exactly what an adopter writes.

## What it shows
- **Real pipeline** — each agent's output is threaded into the next agent's prompt
  (`upstream_output`), so the chain is genuine A→B→C.
- **Web search** — the researcher calls `tools.search.web_search` (Tavily when
  `OAK_SEARCH=tavily` + `TAVILY_API_KEY`; deterministic fake otherwise).
- **Opt-in capture** — with `OAK_CAPTURE_CONTENT=on`, each `chat` span carries the prompt +
  completion and each `execute_tool` span carries the search query + results.
- **Self-defending mesh** — `MESH_LOOP_MODE=storm` drives a writer↔critic loop; the kit's
  detection watcher flags the runaway and the controller trips the per-edge breaker.

## Run it

```sh
docker compose -f examples/research_mesh/compose.yaml up -d --build
```

Trigger one conversation (planner is the entry point):

```sh
curl -X POST http://localhost:8000/start \
  -H 'content-type: application/json' \
  -d '{"conversation_id":"demo-1","user_input":"Summarize 2026 battery-tech breakthroughs"}'
```

Open SigNoz at http://localhost:8080 → **Service Map**, or inspect a `chat` span's
attributes for the captured prompt/output, and an `execute_tool` span for the search I/O.

Per-step replay in the terminal:

```sh
otel-agent-kit explain <trace-id> --replay
```

## Configuration (env)

| Var | Default | Purpose |
|---|---|---|
| `OAK_LLM` | `fake` | `gemini` (needs `GEMINI_API_KEY`) or `real` for live LLM calls |
| `MESH_MODEL` | `gemini-2.5-flash` | model name |
| `OAK_SEARCH` | `fake` | `tavily` (needs `TAVILY_API_KEY`) for real web search |
| `OAK_CAPTURE_CONTENT` | `off` | `on` to record prompts/outputs/tool-I/O on spans |
| `MESH_LOOP_MODE` | `off` | `on` / `storm` to drive the writer↔critic loop |

For the full inspection demo:
```sh
OAK_LLM=gemini GEMINI_API_KEY=… OAK_SEARCH=tavily TAVILY_API_KEY=… \
OAK_CAPTURE_CONTENT=on MESH_LOOP_MODE=storm \
docker compose -f examples/research_mesh/compose.yaml up -d --build
```
