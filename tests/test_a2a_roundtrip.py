import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from amr.a2a import A2AClient, A2AError, create_app


def _recording_tracer(service_name: str) -> tuple[object, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer(service_name), exporter


def test_a2a_call_creates_direct_cross_service_parent_link() -> None:
    alpha_tracer, alpha_exporter = _recording_tracer("agent_alpha")
    beta_tracer, beta_exporter = _recording_tracer("agent_beta")
    server = create_app(tracer=beta_tracer)
    server.register("ping", lambda payload: {"pong": payload})

    with TestClient(server.app) as http_client:
        client = A2AClient(
            "agent_alpha",
            "agent_beta",
            tracer=alpha_tracer,
            http_client=http_client,
        )
        assert client.call("ping", {"value": "hello"}, "http://testserver/a2a") == {
            "pong": {"value": "hello"},
            "_meta": {"cost_usd": 0.0},
        }

    client_span = alpha_exporter.get_finished_spans()[0]
    server_span = beta_exporter.get_finished_spans()[0]
    assert client_span.context.trace_id == server_span.context.trace_id
    assert server_span.parent is not None
    assert server_span.parent.span_id == client_span.context.span_id
    assert client_span.resource.attributes["service.name"] == "agent_alpha"
    assert server_span.resource.attributes["service.name"] == "agent_beta"
    assert client_span.attributes["peer.service"] == "agent_beta"


def test_a2a_client_raises_for_json_rpc_error() -> None:
    tracer, _ = _recording_tracer("agent_alpha")
    server = create_app()
    with TestClient(server.app) as http_client:
        client = A2AClient("agent_alpha", "agent_beta", tracer=tracer, http_client=http_client)
        with pytest.raises(A2AError, match="Method not found"):
            client.call("missing", {}, "http://testserver/a2a")
