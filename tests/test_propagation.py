from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from amr.propagation import extract_from, inject_into


def _tracer(name: str, sampler: ParentBased | None = None) -> trace.Tracer:
    provider = TracerProvider(
        resource=Resource.create({"service.name": name}),
        sampler=sampler,
    )
    return provider.get_tracer(name)


def test_inject_extract_round_trip_preserves_trace_id() -> None:
    tracer = _tracer("propagation-test")
    with tracer.start_as_current_span("source") as span:
        headers: dict[str, str] = {}
        inject_into(headers)

    assert headers["traceparent"].startswith("00-")
    extracted = extract_from(headers)
    extracted_context = trace.get_current_span(extracted).get_span_context()
    assert extracted_context.trace_id == span.get_span_context().trace_id


def test_parent_based_sampler_honors_sampled_remote_parent() -> None:
    sampler = ParentBased(root=TraceIdRatioBased(0.0))
    tracer = _tracer("sampling-test", sampler)
    parent = SpanContext(
        trace_id=0x1234,
        span_id=0x5678,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=trace.TraceState(),
    )
    parent_context = trace.set_span_in_context(NonRecordingSpan(parent), Context())

    with tracer.start_as_current_span("child", context=parent_context) as child:
        assert child.is_recording()
        assert child.get_span_context().trace_id == parent.trace_id
