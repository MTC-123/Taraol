"""Safe, trace-correlated reasoning events (never prompt or model-output content)."""

from typing import Any

from opentelemetry import _logs


def reasoning_event(logger_name: str, agent: str, conversation_id: str, stage: str, **fields: Any) -> None:
    """Emit a content-free reasoning summary under ``logger_name``.

    Note: uses the OpenTelemetry ``_logs`` API, still marked experimental upstream;
    isolated here so a future migration to the stable Events API is one file.
    """

    attributes = {
        "event": "agent_reasoning",
        "agent": agent,
        "conversation_id": conversation_id,
        "reasoning.stage": stage,
    }
    attributes.update({key: value for key, value in fields.items() if value is not None})
    _logs.get_logger(logger_name).emit(
        _logs.LogRecord(body="agent_reasoning", severity_text="INFO", attributes=attributes)
    )
