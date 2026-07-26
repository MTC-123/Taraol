# Reproducible SigNoz with Foundry

The hackathon requires every submission to be reproducible with **Foundry** — SigNoz's
declarative deployment tool. Taraol ships a complete Foundry deployment, so anyone recreates
the exact same backend.

## How it works

```
casting.yaml            what you WANT (SigNoz version, compose flavor) — ~12 lines
      │  foundryctl cast / forge
      ▼
casting.yaml.lock       every resolved decision PINNED (all components + configs)
      ▼
pours/deployment/       the rendered artifact: compose.yaml + ClickHouse / keeper / ingester
                        configs ("do not edit by hand")
```

- **`casting.yaml`** — the intent.
- **`casting.yaml.lock`** — the reproducibility contract; re-running from it yields a
  bit-identical stack.
- **`pours/`** — Foundry's rendered output, the actual multi-service compose stack.

## Two places it ships

1. **Inside the pip package** — `src/taraol/data/signoz/`. Powers `taraol signoz up`, so every
   `pip install taraol` user gets a Foundry-provisioned SigNoz in one command.
2. **In the demo** — `demos/research_mesh/signoz/`. The demo's `compose.yaml` includes this
   Foundry-rendered stack, so the 5-agent demo's SigNoz *is* the Foundry deploy.

## Reproduce it

```bash
# option A: the kit does it for you (uses the bundled Foundry deploy)
taraol signoz up

# option B: run Foundry directly against the committed spec
foundryctl cast -f demos/research_mesh/signoz/casting.yaml
```

Within a few minutes you have SigNoz + ClickHouse + the OpenTelemetry collector + dashboards
running locally — no manual Docker Compose, no missing services, every environment identical.

## SigNoz Cloud

Foundry is for self-hosting. To use SigNoz Cloud instead, skip the deploy and point the
exporter at your endpoint — no code changes:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://ingest.<region>.signoz.cloud:443
OTEL_EXPORTER_OTLP_HEADERS=signoz-ingestion-key=<YOUR_KEY>
```
