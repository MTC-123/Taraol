"""``instrument()`` — the one-call OpenTelemetry bootstrap (idempotent)."""

from collections.abc import Mapping
from pathlib import Path

from opentelemetry import _logs, propagate, trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from .config import Settings
from .cost import CostModel
from .facade import Instrument

# One process installs one provider; a second call reuses it (idempotency guard).
_PROVIDER_INSTALLED = False


def _span_exporter(settings: Settings) -> object:
    if settings.exporter == "http":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter,
        )

        return OTLPSpanExporter(endpoint=settings.endpoint) if settings.endpoint else OTLPSpanExporter()
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=settings.endpoint) if settings.endpoint else OTLPSpanExporter()


def _log_exporter(settings: Settings) -> object:
    if settings.exporter == "http":
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (  # type: ignore[import-not-found]
            OTLPLogExporter,
        )

        return OTLPLogExporter(endpoint=settings.endpoint) if settings.endpoint else OTLPLogExporter()
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

    return OTLPLogExporter(endpoint=settings.endpoint) if settings.endpoint else OTLPLogExporter()


def _install_provider(settings: Settings) -> None:
    resource = Resource.create(
        {"service.name": settings.service_name, "service.namespace": settings.service_namespace}
    )
    provider = TracerProvider(resource=resource, sampler=ParentBased(root=ALWAYS_ON))
    provider.add_span_processor(BatchSpanProcessor(_span_exporter(settings)))
    trace.set_tracer_provider(provider)
    if settings.enable_logs:
        log_provider = LoggerProvider(resource=resource)
        log_provider.add_log_record_processor(BatchLogRecordProcessor(_log_exporter(settings)))
        _logs.set_logger_provider(log_provider)
    # TraceContext MUST stay first so traceparent is on every hop; baggage carries taint.
    propagate.set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )


def _resolve_cost(cost_model: object, settings: Settings) -> CostModel:
    if isinstance(cost_model, CostModel):
        return cost_model
    if isinstance(cost_model, Mapping):
        return CostModel(table=cost_model)
    if isinstance(cost_model, (str, Path)):
        return CostModel(path=cost_model)
    if settings.pricing_path:
        return CostModel(path=settings.pricing_path)
    return CostModel()


def configure(service_name: str | None = None, **overrides: object) -> Settings:
    """Build settings without installing a provider (useful for tests)."""

    return Settings.from_env(service_name, **overrides)


def instrument(
    service_name: str | None = None,
    *,
    settings: Settings | None = None,
    cost_model: object | None = None,
    **overrides: object,
) -> Instrument:
    """Install OpenTelemetry once and return a per-service instrumentation handle.

    Zero-config: ``instrument("planner")`` wires ParentBased(ALWAYS_ON) sampling, an
    OTLP exporter to ``OTEL_EXPORTER_OTLP_ENDPOINT``, W3C trace-context + baggage
    propagation, and the bundled price table. Calling again in the same process reuses
    the installed provider and just returns a handle for the requested service.
    """

    global _PROVIDER_INSTALLED
    resolved = settings or Settings.from_env(service_name, **overrides)
    if not _PROVIDER_INSTALLED:
        _install_provider(resolved)
        _PROVIDER_INSTALLED = True
    tracer = trace.get_tracer(resolved.service_name)
    return Instrument(tracer, resolved, _resolve_cost(cost_model, resolved))
