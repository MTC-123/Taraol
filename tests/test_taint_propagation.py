from opentelemetry import context, propagate, trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from amr import semconv
from amr.propagation import extract_from, inject_into
from amr.taint import Taint, mark_taint, taint_from_baggage, taint_scope


def _recording_tracer(name: str) -> tuple[trace.Tracer, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": name}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer(name), exporter


def test_mark_taint_stamps_content_free_attributes() -> None:
    tracer, exporter = _recording_tracer("planner")
    with tracer.start_as_current_span("chat") as span:
        mark_taint(span, Taint("jailbreak", "planner", 0))
    finished = exporter.get_finished_spans()[0]
    assert finished.attributes[semconv.AGENTMESH_TAINT] is True
    assert finished.attributes[semconv.AGENTMESH_TAINT_CATEGORY] == "jailbreak"
    assert finished.attributes[semconv.AGENTMESH_TAINT_ORIGIN] == "planner"
    assert finished.attributes[semconv.AGENTMESH_TAINT_HOPS] == 0


def test_traceparent_and_taint_baggage_both_survive_inject_extract() -> None:
    # Guards the composite-propagator edit: traceparent MUST remain while baggage
    # carries the injection taint.
    propagate.set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )
    tracer, _ = _recording_tracer("planner")
    headers: dict[str, str] = {}
    with tracer.start_as_current_span("source") as span:
        with taint_scope(Taint("jailbreak", "planner", 1)):
            inject_into(headers)
        trace_id = span.get_span_context().trace_id

    assert headers["traceparent"].startswith("00-")
    assert "baggage" in headers

    extracted = extract_from(headers)
    assert trace.get_current_span(extracted).get_span_context().trace_id == trace_id

    token = context.attach(extracted)
    try:
        carried = taint_from_baggage()
    finally:
        context.detach(token)
    assert carried == Taint("jailbreak", "planner", 1)


def test_clean_context_carries_no_taint() -> None:
    propagate.set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )
    tracer, _ = _recording_tracer("planner")
    headers: dict[str, str] = {}
    with tracer.start_as_current_span("source"):
        inject_into(headers)
    token = context.attach(extract_from(headers))
    try:
        assert taint_from_baggage() is None
    finally:
        context.detach(token)
