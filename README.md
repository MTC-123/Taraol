# Agent Mesh Radar

**See the hidden shape of a multi-agent system before a loop becomes an outage.**

Agent Mesh Radar is an OpenTelemetry-first demo that turns agent-to-agent traffic into an
observable service mesh, then layers cost, loop detection, and an explain-this-loop MCP tool
on top.

> Demo GIF placeholder — added in PLAN 07.

> Architecture diagram placeholder — added in PLAN 07.

## Quickstart

### Prerequisites

- WSL 2 with a native Docker Engine and Docker Compose v2. SigNoz documents Docker Desktop
  on native Windows as unreliable for ClickHouse Keeper.
- At least 4 GB of Docker memory (8 GB recommended).
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for Python tooling.

Start the complete observability stack:

```sh
make up
```

Open [http://localhost:8080](http://localhost:8080). The bundled collector accepts OTLP gRPC
on `localhost:4317` and OTLP HTTP on `localhost:4318`.

```sh
make test
make lint
make down
```

If uv is unavailable, install it with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
For a limited pip-based fallback, create a Python 3.12 virtual environment and install the
development tools listed in `pyproject.toml`; the committed `uv.lock` remains the supported,
reproducible workflow.

## Layers

- **Instrumented-demo layer** (`agents/`) — independently runnable agents, one OTel service each.
- **Detection layer** (`detection/`) — reads telemetry to detect loops and budget breaches.
- **MCP-tool layer** (`mcp_tool/`) — explains observed loops through SigNoz.
- **Shared foundation** (`src/amr/`) — small cross-cutting helpers with no layer coupling.

Layers never import each other’s internals; they communicate through OTLP, HTTP, and SigNoz.

## SigNoz deployment

The repository commits Compose rendered by Foundry `v0.2.11` from
`deploy/signoz/casting.yaml`, with SigNoz pinned to `v0.128.0`. Normal development only needs
Docker Compose; see [the SigNoz deployment notes](deploy/signoz/README.md) to regenerate it.

## Credits

Built on [SigNoz](https://signoz.io/),
[OpenTelemetry](https://opentelemetry.io/),
[A2A](https://a2a-protocol.org/), and
[OpenLLMetry](https://www.traceloop.com/openllmetry).

## License

Apache-2.0. See [LICENSE](LICENSE).


