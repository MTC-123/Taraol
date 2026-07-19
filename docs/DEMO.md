# Agent Mesh Radar — 90-second demo

## Judged path: `make demo` (no secrets)

From a clean checkout, with only Docker and `uv` installed:

```sh
make demo
```

No API key, no Terraform, no manual setup. The script boots the stack in storm
mode (generating a throwaway SigNoz signing key if `.env` is absent), triggers
one unique `demo-loop-*` conversation, and verifies the full beat within 90
seconds — real agents, real loop-watcher detection over ClickHouse, real
controller pause, real trace-correlated audit. The single substitution: the
script delivers the Alertmanager-shaped webhook to the controller itself once
the real `loop_detected` signal appears, because rule evaluation and webhook
delivery inside SigNoz require the credentialed path below. The substitution is
printed loudly when it happens; no SigNoz alert rule is ever created by raw API.

Expected timeline once the conversation starts:

| Time | What you see |
|------|--------------|
| 0–15s | Trace and cost appear; the five-agent mesh renders in the Service Map |
| 10–45s | The cyclic `critic → writer` edge turns red; `loop_detected` fires |
| 30–60s | The controller pauses the writer; `agent_paused` audit log lands |
| 45–90s | The conversation-budget chart flatlines; the terminal prints the post-mortem |

The terminal prints `>>> NOW:` / `>>> WATCH:` cues at each step so a recording
session can follow along without a second person.

## SigNoz click path

1. Open **APM → Service Map**, set the last 5 minutes, and click the red `critic → writer` edge.
2. Open its trace list and select the `demo-loop-*` trace waterfall. Confirm the five named services and repeated writer/critic spans.
3. In the trace details, open **Logs** (or use the trace ID in **Logs**) and filter `trace_id = <trace id>`. Inspect `agent_reasoning`, `loop_detected`, and `agent_paused`.
4. Open **Alerts → Triggered Alerts** (full mode) or the terminal's `[local mode]` webhook line, then **Dashboards → Agent Mesh — Conversation Budget** to show cost flatlining.
5. Run `uv run amr explain <trace-id>` to close with the MCP-grounded pause post-mortem.

## Full path: `make demo-full` (Terraform + SigNoz credential)

This is the same beat with SigNoz itself evaluating the Terraform-provisioned
alert rules and delivering the webhook, verified through the official SigNoz
MCP server.

One-time setup:

1. Copy `.env.example` to `.env`, generate `SIGNOZ_TOKENIZER_JWT_SECRET`, and set `SIGNOZ_API_KEY`.
2. Start SigNoz once with `make up`, sign in at `http://localhost:8080`, and create the `agentmesh-controller` webhook channel with URL `http://controller:8000/alert`. This is the one provider gap: the official Terraform provider manages alerts and route policies but not notification channels. Do not use a raw API request.
   - Known caveat: the local Community-edition UI has been observed rejecting the notification-channel form's backend auth. Retest after `make down && make up` with a fresh login; if it still fails, `make demo` is the supported demo path.
3. Install Terraform 1.8+. Self-hosted Community may gate service accounts behind a license; if so, live MCP/alert provisioning cannot be automated without a supported SigNoz credential.

Then run `make demo-full`. It applies the Terraform route/rules, triggers one
unique conversation, and fails unless trace, cycle, cost, firing alert, pause
audit, flatline, and MCP post-mortem are all verified within 90 seconds.

## Recovery and evidence

Use `POST http://localhost:8002/resume` with `conversation_id`, `agent`, and `trace_id` to resume a paused agent. Record the browser beat with the local screen recorder while following the terminal cues, then convert and commit the evidence:

```sh
ffmpeg -i demo-beat.mp4 -vf "fps=10,scale=960:-1" docs/evidence/demo-beat.gif
```

The recording must show the click path above and contain no authentication errors, blank panels, or placeholder content.
