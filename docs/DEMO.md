# Agent Mesh Radar — 90-second demo

## One-time local setup

1. Copy `.env.example` to `.env` and generate `SIGNOZ_TOKENIZER_JWT_SECRET`. `make up` starts without an API key.
2. Start SigNoz once with `make up`, sign in at `http://localhost:8080`, and create the `agentmesh-controller` webhook channel with URL `http://controller:8000/alert`. This is the one provider gap: the official Terraform provider manages alerts and route policies but not notification channels. Do not use a raw API request.
3. Install Terraform 1.8+. The official SigNoz MCP server can start without a key in HTTP mode, but it cannot query a protected SigNoz instance without either a service-account key or an authenticated bearer session. Self-hosted Community may gate service accounts behind a license; if so, live MCP/alert provisioning cannot be automated without a supported SigNoz credential.

## Timed beat

Run `make demo`. It starts the stack in storm mode, applies the Terraform route/rules, triggers one unique conversation, and fails if trace, cycle, cost, alert/audit, flatline, or MCP post-mortem is not verified within 90 seconds.

Expected beat: 0–15s trace and cost appear; 10–45s the cyclic `critic → writer` edge becomes visible and red; the alert routes to the controller; the writer pause audit appears; the budget chart flatlines; the terminal prints the grounded MCP post-mortem.

## SigNoz click path

1. Open **APM → Service Map**, set the last 5 minutes, and click the red `critic → writer` edge.
2. Open its trace list and select the `demo-loop-*` trace waterfall. Confirm the five named services and repeated writer/critic spans.
3. In the trace details, open **Logs** (or use the trace ID in **Logs**) and filter `trace_id = <trace id>`. Inspect `agent_reasoning`, `loop_detected`, and `agent_paused`.
4. Open **Alerts → Triggered Alerts** to show the firing rule, then **Dashboards → Agent Mesh — Conversation Budget** to show cost flatlining.
5. Run `uv run amr explain <trace-id>` to close with the MCP-grounded pause post-mortem.

## Recovery and evidence

Use `POST http://localhost:8002/resume` with `conversation_id`, `agent`, and `trace_id` to resume a paused agent. Record the browser beat with the local screen recorder and commit `docs/evidence/demo-beat.mp4` plus `docs/evidence/demo-beat.gif`. The recording must show the click path above and contain no authentication errors, blank panels, or placeholder content.
