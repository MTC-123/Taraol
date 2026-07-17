"""OpenTelemetry bootstrap shared by independently deployed agents."""

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


def init_tracing(service_name: str) -> trace.Tracer:
    """Install this process's provider and return its service-specific tracer.

    Agents call this once at process startup.  OpenTelemetry intentionally permits
    only one global provider per process; tests that need multiple services use
    explicitly injected tracers instead.
    """

    resource = Resource.create({"service.name": service_name, "service.namespace": "agent-mesh"})
    provider = TracerProvider(resource=resource, sampler=ParentBased(root=ALWAYS_ON))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    propagate.set_global_textmap(TraceContextTextMapPropagator())
    return trace.get_tracer(service_name)
