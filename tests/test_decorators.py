import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from taraol import agent, chat, record_chat, record_chat_content, semconv, tool
from taraol.config import Settings
from taraol.cost import CostModel
from taraol.facade import Instrument, set_default_instrument


def _install(*, capture: bool = False) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "planner"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    settings = Settings(service_name="planner", capture_content=capture)
    set_default_instrument(Instrument(provider.get_tracer("planner"), settings, CostModel()))
    return exporter


def test_decorators_create_spans_and_record() -> None:
    exporter = _install(capture=True)

    @tool
    def search(q):
        return "3 hits"

    @chat("gpt-4.1-mini")
    def think(prompt):
        record_chat(input_tokens=1000, output_tokens=500)
        record_chat_content(prompt=prompt, completion="ok")
        return "ok"

    @agent(name="planner")
    def plan(task):
        search("climate")
        return think("hi")

    plan("do research")

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert "invoke_agent planner" in spans
    assert "execute_tool search" in spans
    assert "chat gpt-4.1-mini" in spans
    chat_span = spans["chat gpt-4.1-mini"]
    assert chat_span.attributes["agentmesh.cost.direct_usd"] == 0.0012
    assert semconv.GEN_AI_INPUT_MESSAGES in chat_span.attributes  # capture on
    assert spans["execute_tool search"].attributes[semconv.GEN_AI_TOOL_CALL_RESULT] == "3 hits"


def test_bare_agent_and_tool_default_to_func_name() -> None:
    exporter = _install()

    @agent
    def researcher():
        return 1

    @tool
    def fetch():
        return 2

    researcher()
    fetch()
    names = {s.name for s in exporter.get_finished_spans()}
    assert "invoke_agent researcher" in names
    assert "execute_tool fetch" in names


class _GenAIResponse:
    """google-genai shape: usage_metadata.prompt_token_count/candidates_token_count."""

    class _Meta:
        prompt_token_count = 100
        candidates_token_count = 50

    usage_metadata = _Meta()
    text = "hi"


class _OpenAIResponse:
    """OpenAI shape: usage.prompt_tokens/completion_tokens."""

    class _Usage:
        prompt_tokens = 30
        completion_tokens = 7

    usage = _Usage()


def test_chat_auto_extracts_usage_from_returned_response() -> None:
    exporter = _install()

    @chat("gpt-4.1-mini")
    def genai_call():
        return _GenAIResponse()

    @chat("gpt-4.1-mini")
    def openai_call():
        return _OpenAIResponse()

    assert genai_call().text == "hi"  # the raw response passes through untouched
    openai_call()
    spans = exporter.get_finished_spans()
    assert spans[0].attributes[semconv.GEN_AI_USAGE_INPUT_TOKENS] == 100
    assert spans[0].attributes[semconv.GEN_AI_USAGE_OUTPUT_TOKENS] == 50
    assert spans[0].attributes["agentmesh.cost.direct_usd"] > 0
    assert spans[1].attributes[semconv.GEN_AI_USAGE_INPUT_TOKENS] == 30


def test_chat_auto_captures_content_when_opted_in() -> None:
    exporter = _install(capture=True)

    @chat("gpt-4.1-mini")
    def think(prompt):
        return _GenAIResponse()  # .text == "hi"

    think("what is otel?")
    span = exporter.get_finished_spans()[0]
    assert "what is otel?" in span.attributes[semconv.GEN_AI_INPUT_MESSAGES]
    assert "hi" in span.attributes[semconv.GEN_AI_OUTPUT_MESSAGES]


def test_chat_auto_content_stays_off_by_default() -> None:
    exporter = _install()  # capture_content off

    @chat("gpt-4.1-mini")
    def think(prompt):
        return _GenAIResponse()

    think("secret prompt")
    span = exporter.get_finished_spans()[0]
    assert semconv.GEN_AI_INPUT_MESSAGES not in span.attributes
    assert semconv.GEN_AI_OUTPUT_MESSAGES not in span.attributes


def test_explicit_record_chat_content_wins_over_auto_capture() -> None:
    exporter = _install(capture=True)

    @chat("gpt-4.1-mini")
    def think(prompt):
        record_chat_content(prompt="explicit-p", completion="explicit-c")
        return _GenAIResponse()  # auto would capture prompt/"hi"

    think("auto-prompt")
    span = exporter.get_finished_spans()[0]
    assert "explicit-p" in span.attributes[semconv.GEN_AI_INPUT_MESSAGES]
    assert "auto-prompt" not in span.attributes[semconv.GEN_AI_INPUT_MESSAGES]


def test_explicit_record_chat_wins_over_auto_extraction() -> None:
    exporter = _install()

    @chat("gpt-4.1-mini")
    def call():
        record_chat(input_tokens=1, output_tokens=2)
        return _GenAIResponse()  # would auto-extract 100/50 if not already recorded

    call()
    span = exporter.get_finished_spans()[0]
    assert span.attributes[semconv.GEN_AI_USAGE_INPUT_TOKENS] == 1
    assert span.attributes[semconv.GEN_AI_USAGE_OUTPUT_TOKENS] == 2


def test_decorator_without_instrument_raises() -> None:
    set_default_instrument(None)  # type: ignore[arg-type]

    @agent
    def orphan():
        return 1

    with pytest.raises(RuntimeError, match="instrument"):
        orphan()
