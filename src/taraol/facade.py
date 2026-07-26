"""The instrumentation handle returned by :func:`taraol.instrument`.

Provides the small set of context managers a caller composes to get correct gen_ai
spans, cost rollup, and the taint/breaker/provenance signals — without touching any
OpenTelemetry object directly.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from opentelemetry.trace import SpanKind, Tracer

from . import capture, semconv
from .attributes import AttrNames, attrs
from .config import Settings
from .cost import CostModel, add_to_request_cost
from .events import reasoning_event
from .taint import Taint, mark_taint, taint_from_baggage, taint_scope

_conversation_id: ContextVar[str | None] = ContextVar("oak_conversation_id", default=None)


@dataclass(frozen=True, slots=True)
class ExperimentContext:
    """The active AgentLab experiment — stamped on every span while it is in scope.

    ``metadata`` is already keyed by ``experiment.*`` attribute names (description / author /
    commit / python.version / …), so it merges straight onto a span.
    """

    id: str
    variant: str
    run_id: str
    metadata: Mapping[str, str] = field(default_factory=dict)


_experiment: ContextVar[ExperimentContext | None] = ContextVar("oak_experiment", default=None)


def current_experiment() -> ExperimentContext | None:
    return _experiment.get()


@contextmanager
def use_experiment(ctx: ExperimentContext) -> Iterator[None]:
    """Make ``ctx`` the active experiment for the duration of the block (spans get tagged)."""

    token = _experiment.set(ctx)
    try:
        yield
    finally:
        _experiment.reset(token)


def _experiment_tags(settings: Settings) -> dict[str, str]:
    """Experiment attributes to stamp on a span: the active ContextVar wins, else Settings."""

    ctx = _experiment.get()
    if ctx is not None:
        tags = {
            semconv.EXPERIMENT_ID: ctx.id,
            semconv.EXPERIMENT_VARIANT: ctx.variant,
            semconv.EXPERIMENT_RUN_ID: ctx.run_id,
        }
        tags.update({k: v for k, v in ctx.metadata.items() if v})
        return tags
    tags = {}
    if settings.experiment_id:
        tags[semconv.EXPERIMENT_ID] = settings.experiment_id
    if settings.experiment_variant:
        tags[semconv.EXPERIMENT_VARIANT] = settings.experiment_variant
    if settings.experiment_run_id:
        tags[semconv.EXPERIMENT_RUN_ID] = settings.experiment_run_id
    return tags


# Process-default handle so the decorator API (@agent/@chat/@tool) works without
# threading the Instrument through every call. Set by instrument().
_default_instrument: "Instrument | None" = None


def current_conversation_id() -> str | None:
    return _conversation_id.get()


def set_default_instrument(instrument: "Instrument") -> None:
    global _default_instrument
    _default_instrument = instrument


def get_default_instrument() -> "Instrument":
    if _default_instrument is None:
        raise RuntimeError("call instrument(...) before using the @agent/@chat/@tool decorators")
    return _default_instrument


class ChatSpan:
    """Wraps a chat span; ``record`` attaches usage and finalizes direct cost on exit."""

    def __init__(
        self, span: object, model: str, names: AttrNames, cost_model: CostModel, settings: Settings
    ) -> None:
        self._span = span
        self._model = model
        self._names = names
        self._cost = cost_model
        self._settings = settings
        self._input = 0
        self._output = 0
        self._finish = "unknown"
        self._recorded = False
        self._content_recorded = False

    @property
    def span(self) -> object:
        return self._span

    @property
    def recorded(self) -> bool:
        """True once usage was recorded (lets the @chat auto-extractor stay hands-off)."""

        return self._recorded

    @property
    def content_recorded(self) -> bool:
        """True once content capture was attempted (explicit call wins over auto-capture)."""

        return self._content_recorded

    def record(self, *, input_tokens: int, output_tokens: int, finish_reason: str = "stop") -> None:
        self._input, self._output, self._finish = input_tokens, output_tokens, finish_reason
        self._recorded = True
        self._span.set_attribute(semconv.GEN_AI_USAGE_INPUT_TOKENS, input_tokens)  # type: ignore[attr-defined]
        self._span.set_attribute(semconv.GEN_AI_USAGE_OUTPUT_TOKENS, output_tokens)  # type: ignore[attr-defined]
        self._span.set_attribute(semconv.GEN_AI_RESPONSE_FINISH_REASONS, (finish_reason,))  # type: ignore[attr-defined]

    def record_content(self, *, prompt: str, completion: str, system: str | None = None) -> None:
        """Capture prompt/completion as gen_ai messages — ONLY when capture_content is on."""

        self._content_recorded = True
        if not self._settings.capture_content:
            return
        limit = self._settings.content_max_chars
        inp, t1 = capture.encode_messages("user", prompt, limit)
        out, t2 = capture.encode_messages("assistant", completion, limit)
        self._span.set_attribute(semconv.GEN_AI_INPUT_MESSAGES, inp)  # type: ignore[attr-defined]
        self._span.set_attribute(semconv.GEN_AI_OUTPUT_MESSAGES, out)  # type: ignore[attr-defined]
        truncated = t1 or t2
        if system:
            sysmsg, t3 = capture.encode_messages("system", system, limit)
            self._span.set_attribute(semconv.GEN_AI_SYSTEM_INSTRUCTIONS, sysmsg)  # type: ignore[attr-defined]
            truncated = truncated or t3
        if truncated:
            self._span.set_attribute(self._names.content_truncated, True)  # type: ignore[attr-defined]

    def _finalize(self) -> None:
        usd, unpriced = self._cost.cost_of(self._model, self._input, self._output)
        self._span.set_attribute(self._names.cost_direct_usd, usd)  # type: ignore[attr-defined]
        if unpriced:
            self._span.set_attribute(self._names.cost_unpriced, True)  # type: ignore[attr-defined]
        add_to_request_cost(usd)


class ToolSpan:
    """Wraps an execute_tool span; captures tool arguments/result only when enabled."""

    def __init__(self, span: object, names: AttrNames, settings: Settings) -> None:
        self._span = span
        self._names = names
        self._settings = settings

    @property
    def span(self) -> object:
        return self._span

    def set_arguments(self, arguments: str) -> None:
        if not self._settings.capture_content:
            return
        text, tr = capture.truncate(arguments, self._settings.content_max_chars)
        self._span.set_attribute(semconv.GEN_AI_TOOL_CALL_ARGUMENTS, text)  # type: ignore[attr-defined]
        if tr:
            self._span.set_attribute(self._names.content_truncated, True)  # type: ignore[attr-defined]

    def set_result(self, result: str) -> None:
        if not self._settings.capture_content:
            return
        text, tr = capture.truncate(result, self._settings.content_max_chars)
        self._span.set_attribute(semconv.GEN_AI_TOOL_CALL_RESULT, text)  # type: ignore[attr-defined]
        if tr:
            self._span.set_attribute(self._names.content_truncated, True)  # type: ignore[attr-defined]


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
            attributes.update(_experiment_tags(self.settings))
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
        attributes.update(_experiment_tags(self.settings))
        with self.tracer.start_as_current_span(
            f"chat {model}", kind=SpanKind.CLIENT, attributes=attributes
        ) as span:
            chat = ChatSpan(span, model, self.names, self.cost_model, self.settings)
            try:
                yield chat
            finally:
                chat._finalize()

    @contextmanager
    def tool(self, tool_name: str, *, arguments: str | None = None) -> Iterator[ToolSpan]:
        attributes = {semconv.GEN_AI_OPERATION_NAME: semconv.EXECUTE_TOOL}
        attributes.update(_experiment_tags(self.settings))
        with self.tracer.start_as_current_span(
            f"execute_tool {tool_name}",
            kind=SpanKind.INTERNAL,
            attributes=attributes,
        ) as span:
            tool = ToolSpan(span, self.names, self.settings)
            if arguments is not None:
                tool.set_arguments(arguments)
            yield tool

    def reasoning(self, stage: str, *, summary: str | None = None, **fields: object) -> None:
        # Reasoning summary text is content — only include it when capture is enabled.
        if summary is not None and self.settings.capture_content:
            text, _ = capture.truncate(summary, self.settings.content_max_chars)
            fields["reasoning.summary"] = text
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
