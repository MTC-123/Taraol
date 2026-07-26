"""Trace-correlated OTLP audit logs for enforcement actions."""

from datetime import UTC, datetime
from typing import Protocol

from opentelemetry import _logs
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from .signals import OTLPSignalEmitter, Signal


class AuditEmitter(Protocol):
    def emit(
        self,
        event: str,
        *,
        conversation_id: str,
        agent: str,
        trace_id: str,
        reason: str,
        alert_name: str,
        enforcement_mode: str,
        edge: str = "",
    ) -> None: ...


class RecordingAuditEmitter:
    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    def emit(self, event: str, **fields: str) -> None:
        self.events.append({"event": event} | fields)


class OTLPAuditEmitter:
    def __init__(self, endpoint: str) -> None:
        self.logger_provider = LoggerProvider(
            resource=Resource.create(
                {"service.name": "alert-controller", "service.namespace": "agent-mesh"}
            )
        )
        self.logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True))
        )
        self._logger = self.logger_provider.get_logger("agentmesh.audit")

    def emit(
        self,
        event: str,
        *,
        conversation_id: str,
        agent: str,
        trace_id: str,
        reason: str,
        alert_name: str,
        enforcement_mode: str,
        edge: str = "",
    ) -> None:
        attributes = {
            "conversation_id": conversation_id,
            "agent": agent,
            "trace_id": trace_id,
            "reason": reason,
            "alert_name": alert_name,
            "enforcement_mode": enforcement_mode,
            "ts": datetime.now(UTC).isoformat(),
        }
        if edge:
            attributes["edge"] = edge
        signal = Signal(event, conversation_id, None, None, None, trace_id, datetime.now(UTC))
        self._logger.emit(
            _logs.LogRecord(  # type: ignore[attr-defined]
                body=event,
                severity_text="INFO",
                attributes=attributes,
                context=OTLPSignalEmitter._context(signal),
            )
        )

    def shutdown(self) -> None:
        self.logger_provider.shutdown()
