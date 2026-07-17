"""Expose Beta's minimal A2A ping method."""

import os
from typing import Any

from amr.a2a import create_app, run
from amr.otel_setup import init_tracing


def ping(payload: dict[str, Any]) -> dict[str, Any]:
    return {"pong": payload}


def main() -> None:
    service_name = os.getenv("OTEL_SERVICE_NAME", "agent_beta")
    tracer = init_tracing(service_name)
    server = create_app(tracer=tracer)
    server.register("ping", ping)
    run(service_name, 8001, server)


if __name__ == "__main__":
    main()
