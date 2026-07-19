"""Safe, trace-correlated events emitted by demo agents."""

from typing import Any

from opentelemetry import _logs


def reasoning_event(agent: str, conversation_id: str, stage: str, **fields: Any) -> None:
    """Emit an auditable reasoning summary without prompt or model-output content."""

    attributes = {
        "event": "agent_reasoning",
        "agent": agent,
        "conversation_id": conversation_id,
        "reasoning.stage": stage,
    }
    attributes.update({key: value for key, value in fields.items() if value is not None})
    _logs.get_logger("agentmesh.reasoning").emit(
        _logs.LogRecord(body="agent_reasoning", severity_text="INFO", attributes=attributes)
    )
