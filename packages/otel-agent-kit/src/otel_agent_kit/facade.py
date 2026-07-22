"""The instrumentation handle returned by :func:`otel_agent_kit.instrument`.

Provides the small set of context managers a caller composes to get correct gen_ai
spans, cost rollup, and the taint/breaker/provenance signals — without touching any
OpenTelemetry object directly.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry.trace import SpanKind, Tracer

from . import semconv
from .attributes import AttrNames, attrs
from .config import Settings
from .cost import CostModel, add_to_request_cost
from .events import reasoning_event
from .taint import Taint, mark_taint, taint_from_baggage, taint_scope

_conversation_id: ContextVar[str | None] = ContextVar("oak_conversation_id", default=None)


def current_conversation_id() -> str | None:
    return _conversation_id.get()


class ChatSpan:
    """Wraps a chat span; ``record`` attaches usage and finalizes cost on exit."""

    def __init__(self, span: object, model: str, names: AttrNames, cost_model: CostModel) -> None:
        self._span = span
        self._model = model
        self._names = names
        self._cost = cost_model
        self._input = 0
        self._output = 0
        self._finish = "unknown"

    @property
    def span(self) -> object:
        return self._span

    def record(self, *, input_tokens: int, output_tokens: int, finish_reason: str = "stop") -> None:
        self._input, self._output, self._finish = input_tokens, output_tokens, finish_reason
        self._span.set_attribute(semconv.GEN_AI_USAGE_INPUT_TOKENS, input_tokens)  # type: ignore[attr-defined]
        self._span.set_attribute(semconv.GEN_AI_USAGE_OUTPUT_TOKENS, output_tokens)  # type: ignore[attr-defined]
        self._span.set_attribute(semconv.GEN_AI_RESPONSE_FINISH_REASONS, (finish_reason,))  # type: ignore[attr-defined]

    def _finalize(self) -> None:
        usd, unpriced = self._cost.cost_of(self._model, self._input, self._output)
        self._span.set_attribute(self._names.cost_usd, usd)  # type: ignore[attr-defined]
        if unpriced:
            self._span.set_attribute(self._names.cost_unpriced, True)  # type: ignore[attr-defined]
        add_to_request_cost(usd)


class Instrument:
    """A per-service instrumentation handle over one process-global provider."""

    def __init__(self, tracer: Tracer, settings: Settings, cost_model: CostModel) -> None:
        self.tracer = tracer
        self.settings = settings
        self.cost_model = cost_model
        self.names: AttrNames = attrs(settings.attr_namespace)

    @contextmanager
    def agent(self, name: str, conversation_id: str | None = None) -> Iterator[object]:
        token = _conversation_id.set(conversation_id) if conversation_id is not None else None
        try:
            attributes = {
                semconv.GEN_AI_OPERATION_NAME: semconv.INVOKE_AGENT,
                semconv.GEN_AI_AGENT_NAME: name,
            }
            if conversation_id is not None:
                attributes[semconv.GEN_AI_CONVERSATION_ID] = conversation_id
            with self.tracer.start_as_current_span(
                f"invoke_agent {name}", kind=SpanKind.INTERNAL, attributes=attributes
            ) as span:
                yield span
        finally:
            if token is not None:
                _conversation_id.reset(token)

    @contextmanager
    def chat(self, model: str, *, provider: str | None = None) -> Iterator[ChatSpan]:
        attributes = {
            semconv.GEN_AI_OPERATION_NAME: semconv.CHAT,
            semconv.GEN_AI_PROVIDER_NAME: provider or self.settings.provider_name,
            semconv.GEN_AI_REQUEST_MODEL: model,
            semconv.GEN_AI_USAGE_INPUT_TOKENS: 0,
            semconv.GEN_AI_USAGE_OUTPUT_TOKENS: 0,
            semconv.GEN_AI_RESPONSE_FINISH_REASONS: ("unknown",),
        }
        conversation_id = _conversation_id.get()
        if conversation_id is not None:
            attributes[semconv.GEN_AI_CONVERSATION_ID] = conversation_id
        with self.tracer.start_as_current_span(
            f"chat {model}", kind=SpanKind.CLIENT, attributes=attributes
        ) as span:
            chat = ChatSpan(span, model, self.names, self.cost_model)
            try:
                yield chat
            finally:
                chat._finalize()

    @contextmanager
    def tool(self, tool_name: str) -> Iterator[object]:
        with self.tracer.start_as_current_span(
            f"execute_tool {tool_name}",
            kind=SpanKind.INTERNAL,
            attributes={semconv.GEN_AI_OPERATION_NAME: semconv.EXECUTE_TOOL},
        ) as span:
            yield span

    def reasoning(self, stage: str, **fields: object) -> None:
        reasoning_event(
            self.names.reasoning_logger(),
            self.settings.service_name,
            _conversation_id.get() or "",
            stage,
            **fields,
        )

    # --- Tier-1 security/quality overlays -------------------------------------

    def mark_injection(self, category: str, span: object | None = None) -> Taint:
        """Stamp taint on ``span`` (or the active chat/agent span) with this service as origin."""

        from opentelemetry import trace

        target = span if span is not None else trace.get_current_span()
        taint = Taint(category, self.settings.service_name, 0)
        mark_taint(target, taint, self.names)
        return taint

    def taint_scope(self, taint: Taint):
        """Propagate a taint marker to downstream hops made within the scope."""

        return taint_scope(taint, self.names)

    def inherited_taint(self) -> Taint | None:
        return taint_from_baggage(self.names)

    def flag_output(self, category: str, span: object) -> None:
        """Mark ``span`` as the origin of bad output for provenance backtracking."""

        span.set_attribute(self.names.output_flagged, True)  # type: ignore[attr-defined]
        span.set_attribute(self.names.output_category, category)  # type: ignore[attr-defined]
