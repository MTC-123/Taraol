"""Structured, trace-correlated OTLP signal emission."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from opentelemetry import _logs
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
from opentelemetry.trace.propagation import set_span_in_context


@dataclass(frozen=True, slots=True)
class Signal:
    signal: str
    conversation_id: str | None
    edge: str | None
    hops: int | None
    cost_usd: float | None
    trace_id: str | None
    ts: datetime
    origin_span_id: str | None = None
    # Injection-taint context (content-free): the flagged category, the originating
    # service, and the comma-joined blast-radius services reached by the taint.
    category: str | None = None
    origin: str | None = None
    blast: str | None = None
    # Why a loop was classified runaway: "repeated_state" | "iteration_cap" | "cost_budget".
    reason: str | None = None

    def attributes(self) -> dict[str, str | int | float]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None and key not in {"ts", "origin_span_id"}
        } | {"ts": self.ts.astimezone(UTC).isoformat()}


class SignalEmitter(Protocol):
    def emit(self, signal: Signal) -> None: ...

    def shutdown(self) -> None: ...


class RecordingEmitter:
    """Test seam that records signals without initializing telemetry SDK globals."""

    def __init__(self) -> None:
        self.signals: list[Signal] = []

    def emit(self, signal: Signal) -> None:
        self.signals.append(signal)

    def shutdown(self) -> None:
        return None


class OTLPSignalEmitter:
    def __init__(self, endpoint: str) -> None:
        resource = Resource.create(
            {"service.name": "loop-watcher", "service.namespace": "agent-mesh"}
        )
        self.logger_provider = LoggerProvider(resource=resource)
        self.logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True))
        )
        self.meter_provider = MeterProvider(
            metric_readers=[
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=endpoint, insecure=True),
                    export_interval_millis=5000,
                )
            ],
            resource=resource,
        )
        self._logger = self.logger_provider.get_logger("agentmesh.detection")
        meter = self.meter_provider.get_meter("agentmesh.detection")
        self._loops = meter.create_counter("agentmesh.loops.detected")
        self._budgets = meter.create_counter("agentmesh.budget.breaches")
        self._injections = meter.create_counter("agentmesh.injection.detected")
        self._unhealthy_edges = meter.create_counter("agentmesh.edges.unhealthy")
        self._xconv_loops = meter.create_counter("agentmesh.xconv.loops.detected")

    @staticmethod
    def _context(signal: Signal):
        if not signal.trace_id or len(signal.trace_id) != 32:
            return None
        try:
            trace_id = int(signal.trace_id, 16)
            span_id = int(signal.origin_span_id, 16) if signal.origin_span_id else 1
        except ValueError:
            return None
        if trace_id == 0 or span_id == 0:
            return None
        span_context = SpanContext(trace_id, span_id, True, TraceFlags.SAMPLED)
        return set_span_in_context(NonRecordingSpan(span_context))

    def emit(self, signal: Signal) -> None:
        attributes = signal.attributes()
        self._logger.emit(
            _logs.LogRecord(  # type: ignore[attr-defined]
                body=signal.signal,
                severity_text="WARN",
                attributes=attributes,
                context=self._context(signal),
            )
        )
        if signal.signal == "loop_detected":
            self._loops.add(1)
        elif signal.signal == "budget_exceeded":
            self._budgets.add(1)
        elif signal.signal == "injection_detected":
            self._injections.add(1)
        elif signal.signal == "edge_unhealthy":
            self._unhealthy_edges.add(1)
        elif signal.signal == "xconv_loop_detected":
            self._xconv_loops.add(1)

    def shutdown(self) -> None:
        self.logger_provider.shutdown()
        self.meter_provider.shutdown()
