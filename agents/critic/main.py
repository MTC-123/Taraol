"""Entrypoint for the critic service."""

import os

from agents.common import register_agent
from amr.a2a import create_app, run
from amr.otel_setup import init_tracing


def main() -> None:
    name = "critic"
    tracer = init_tracing(os.getenv("OTEL_SERVICE_NAME", name))
    server = create_app(tracer=tracer)
    register_agent(server, name, tracer)
    run(name, 8000, server)


if __name__ == "__main__":
    main()
