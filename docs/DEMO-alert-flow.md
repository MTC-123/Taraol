# Legacy alert-to-pause notes

The canonical current runbook is [DEMO.md](DEMO.md). These notes remain for the
approval-mode and manual-recovery details below.

## One-time SigNoz UI setup

1. Start the stack with `make up`, then open `http://localhost:8080`.
2. Go to **Settings → Account Settings → Notification Channels → New Channel**. Create
   `agentmesh-controller` as a Webhook with URL `http://controller:8000/alert`. Use **Test**;
   the controller must return HTTP 200. Save the sanitized Alertmanager body as
   `signoz/alerts/webhook-payload.fixture.json`.
3. Go to **Alerts → Configurations → Routing Policies** and add policy
   `agentmesh-controller`: expression `amr.enforcement = "controller"`, channel
   `agentmesh-controller`.
4. Apply the committed rules and routing policy through Terraform (`make demo`). The official
   provider does not create notification channels, so the webhook in step 2 remains the one-time
   UI action. Export saved rules read-only, sanitize instance IDs/timestamps, and replace the
   committed JSON with that export.

## Auto-mode live beat

1. Recreate the agents in storm mode: `AMR_LOOP_MODE=storm docker compose up -d --force-recreate planner researcher writer critic router loop-watcher controller`.
2. Start a conversation: `curl -X POST http://localhost:8000/start -H "content-type: application/json" -d "{\"conversation_id\":\"demo-loop-1\"}"`.
3. In SigNoz, open **Logs** and filter `signal = 'loop_detected'`; then open **Alerts → Triggered Alerts**. The `loop-detected` rule becomes firing within its one-minute evaluation window.
4. Inspect controller output and Logs for `body = 'agent_paused'`. Its `conversation_id` and
   `trace_id` match the loop signal; writer returns `{ "status": "paused" }` for further work
   and cost stops growing on the critic → writer edge.
5. Record the elapsed signal-to-audit time and capture the Logs, Triggered Alert, and paused
   response as `docs/evidence/alert-flow-<date>.png` or a GIF. The controller-to-audit path was
   locally verified in approximately six seconds (including the OTLP batch export); record the
   SigNoz-rule-to-audit time during the UI run.

## Approval and recovery

- Approval mode: recreate controller with `AMR_ENFORCE=approve`; `POST /alert` returns an
  approval token, and `POST http://localhost:8002/approve` with `{ "token": "..." }` performs
  the pause.
- Recovery: `curl -X POST http://localhost:8002/resume -H "content-type: application/json" -d
  "{\"conversation_id\":\"demo-loop-1\",\"agent\":\"writer\",\"trace_id\":\"<trace-id>\"}"`.
  This emits `agent_resumed`. A pause also expires automatically after `AMR_PAUSE_TTL_SEC`
  (five minutes by default).

## Local verification recorded

A real Alertmanager-shaped fixture was posted to the running controller. It paused writer for
`controller-e2e`; a request made from the Compose network returned
`{"status":"paused","conversation_id":"controller-e2e"}`. ClickHouse then contained both
trace-correlated `agent_paused` and `agent_resumed` OTLP logs. The local SigNoz UI currently
loads its workspace shell but rejects the notification-channel form's backend authentication;
complete the one-time UI steps above once that local SigNoz session is restored. No alert or
channel was created by raw API.
