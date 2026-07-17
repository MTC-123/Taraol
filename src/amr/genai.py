"""OpenTelemetry helpers for the GenAI spans emitted by every agent."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry.trace import SpanKind, Tracer

from . import semconv
from .llm import LLMResult


def _provider_name() -> str:
    return os.environ.get("AMR_LLM_PROVIDER", os.environ.get("AMR_LLM", "fake"))


@contextmanager
def chat_span(tracer: Tracer, model: str) -> Iterator[object]:
    """Create a chat client span; callers record the result before leaving it."""

    attributes = {
        semconv.GEN_AI_OPERATION_NAME: semconv.CHAT,
        semconv.GEN_AI_PROVIDER_NAME: _provider_name(),
        semconv.GEN_AI_REQUEST_MODEL: model,
        # Defaults ensure content is never captured and the query fields exist even on errors.
        semconv.GEN_AI_USAGE_INPUT_TOKENS: 0,
        semconv.GEN_AI_USAGE_OUTPUT_TOKENS: 0,
        semconv.GEN_AI_RESPONSE_FINISH_REASONS: ("unknown",),
    }
    with tracer.start_as_current_span(
        f"chat {model}", kind=SpanKind.CLIENT, attributes=attributes
    ) as span:
        yield span


def record_chat_result(span: object, result: LLMResult) -> None:
    """Attach provider-reported (or deterministic fake) usage without recording content."""

    span.set_attribute(semconv.GEN_AI_USAGE_INPUT_TOKENS, result.input_tokens)  # type: ignore[attr-defined]
    span.set_attribute(semconv.GEN_AI_USAGE_OUTPUT_TOKENS, result.output_tokens)  # type: ignore[attr-defined]
    span.set_attribute(semconv.GEN_AI_RESPONSE_FINISH_REASONS, (result.finish_reason,))  # type: ignore[attr-defined]


@contextmanager
def tool_span(tracer: Tracer, tool_name: str) -> Iterator[object]:
    with tracer.start_as_current_span(
        f"execute_tool {tool_name}",
        kind=SpanKind.INTERNAL,
        attributes={semconv.GEN_AI_OPERATION_NAME: semconv.EXECUTE_TOOL},
    ) as span:
        yield span


@contextmanager
def agent_span(tracer: Tracer, agent_name: str, conversation_id: str) -> Iterator[object]:
    with tracer.start_as_current_span(
        f"invoke_agent {agent_name}",
        kind=SpanKind.INTERNAL,
        attributes={
            semconv.GEN_AI_OPERATION_NAME: semconv.INVOKE_AGENT,
            semconv.GEN_AI_AGENT_NAME: agent_name,
            semconv.GEN_AI_CONVERSATION_ID: conversation_id,
        },
    ) as span:
        yield span
