from opentelemetry import context, propagate
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from otel_agent_kit import attrs
from otel_agent_kit.propagation import extract_from, inject_into
from otel_agent_kit.taint import Taint, mark_taint, taint_from_baggage, taint_scope


def test_mark_taint_uses_namespace() -> None:
    names = attrs("myco")
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "planner"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("planner")
    with tracer.start_as_current_span("chat") as span:
        mark_taint(span, Taint("jailbreak", "planner", 0), names)
    stamped = exporter.get_finished_spans()[0]
    assert stamped.attributes["myco.taint"] is True
    assert stamped.attributes["myco.taint.origin"] == "planner"


def test_taint_and_traceparent_survive_propagation() -> None:
    propagate.set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )
    names = attrs("agentmesh")
    provider = TracerProvider(resource=Resource.create({"service.name": "planner"}))
    tracer = provider.get_tracer("planner")
    headers: dict[str, str] = {}
    with tracer.start_as_current_span("s"):
        with taint_scope(Taint("jailbreak", "planner", 1), names):
            inject_into(headers)
    assert headers["traceparent"].startswith("00-")
    assert "baggage" in headers
    token = context.attach(extract_from(headers))
    try:
        assert taint_from_baggage(names) == Taint("jailbreak", "planner", 1)
    finally:
        context.detach(token)
