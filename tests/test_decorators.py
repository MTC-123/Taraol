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


def test_decorator_without_instrument_raises() -> None:
    set_default_instrument(None)  # type: ignore[arg-type]

    @agent
    def orphan():
        return 1

    with pytest.raises(RuntimeError, match="instrument"):
        orphan()
