import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from amr import semconv
from amr.a2a import A2AClient, EdgeBrokenError
from amr.breaker import edge_key, get_registry


class _ExplodingHttp:
    """A client whose post must never be called when the edge is open."""

    def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("dispatch happened despite an open breaker")


def test_open_edge_short_circuits_without_dispatch_and_stamps_span() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "writer"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("writer")

    edge = edge_key("writer", "critic")
    registry = get_registry()
    registry.trip(edge)
    try:
        client = A2AClient("writer", "critic", tracer=tracer, http_client=_ExplodingHttp())
        with pytest.raises(EdgeBrokenError):
            client.call("work", {}, "http://critic:8000/a2a")
    finally:
        registry.reset(edge)

    span = exporter.get_finished_spans()[0]
    assert span.attributes[semconv.AGENTMESH_BREAKER_STATE] == "open"
    assert span.attributes[semconv.AGENTMESH_BREAKER_EDGE] == edge
