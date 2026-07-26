from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from taraol import semconv
from taraol.config import Settings
from taraol.cost import CostModel
from taraol.facade import Instrument


def _kit(namespace: str = "agentmesh") -> tuple[Instrument, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "planner"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    settings = Settings(service_name="planner", attr_namespace=namespace)
    return Instrument(provider.get_tracer("planner"), settings, CostModel()), exporter


def test_chat_span_carries_gen_ai_semconv_and_cost() -> None:
    kit, exporter = _kit()
    with kit.agent("planner", "conv-1"), kit.chat("gpt-4.1-mini") as chat:
        chat.record(input_tokens=1000, output_tokens=500)
    spans = {span.name: span for span in exporter.get_finished_spans()}
    chat_span = spans["chat gpt-4.1-mini"]
    assert chat_span.attributes[semconv.GEN_AI_OPERATION_NAME] == "chat"
    assert chat_span.attributes[semconv.GEN_AI_USAGE_INPUT_TOKENS] == 1000
    assert chat_span.attributes[semconv.GEN_AI_CONVERSATION_ID] == "conv-1"
    # 1000/1000*0.0004 + 500/1000*0.0016 = 0.0012
    assert chat_span.attributes["agentmesh.cost.direct_usd"] == 0.0012


def test_attr_namespace_is_configurable() -> None:
    kit, exporter = _kit(namespace="myco")
    with kit.agent("planner", "c"), kit.chat("gpt-4.1-mini") as chat:
        chat.record(input_tokens=1000, output_tokens=0)
    chat_span = next(s for s in exporter.get_finished_spans() if s.name.startswith("chat"))
    assert "myco.cost.direct_usd" in chat_span.attributes
    assert "agentmesh.cost.direct_usd" not in chat_span.attributes


def test_content_capture_off_by_default_records_no_content() -> None:
    kit, exporter = _kit()
    with kit.chat("gpt-4.1-mini") as chat:
        chat.record(input_tokens=5, output_tokens=5)
        chat.record_content(prompt="secret prompt", completion="secret output")
    chat_span = exporter.get_finished_spans()[0]
    assert semconv.GEN_AI_INPUT_MESSAGES not in chat_span.attributes
    assert semconv.GEN_AI_OUTPUT_MESSAGES not in chat_span.attributes


def test_content_capture_on_records_messages_and_truncates() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "planner"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    settings = Settings(service_name="planner", capture_content=True, content_max_chars=8)
    kit = Instrument(provider.get_tracer("planner"), settings, CostModel())
    with kit.chat("gpt-4.1-mini") as chat:
        chat.record(input_tokens=5, output_tokens=5)
        chat.record_content(prompt="a short prompt that is long", completion="ok")
    chat_span = exporter.get_finished_spans()[0]
    assert '"role": "user"' in chat_span.attributes[semconv.GEN_AI_INPUT_MESSAGES]
    assert "truncated" in chat_span.attributes[semconv.GEN_AI_INPUT_MESSAGES]
    assert chat_span.attributes["agentmesh.content.truncated"] is True


def test_tool_span_captures_io_only_when_enabled() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "researcher"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    settings = Settings(service_name="researcher", capture_content=True)
    kit = Instrument(provider.get_tracer("researcher"), settings, CostModel())
    with kit.tool("search", arguments="climate 2026") as t:
        t.set_result("3 hits")
    span = exporter.get_finished_spans()[0]
    assert span.attributes[semconv.GEN_AI_TOOL_CALL_ARGUMENTS] == "climate 2026"
    assert span.attributes[semconv.GEN_AI_TOOL_CALL_RESULT] == "3 hits"


def test_unpriced_model_flags_zero_cost() -> None:
    kit, exporter = _kit()
    with kit.chat("mystery-model") as chat:
        chat.record(input_tokens=10, output_tokens=10)
    chat_span = exporter.get_finished_spans()[0]
    assert chat_span.attributes["agentmesh.cost.direct_usd"] == 0.0
    assert chat_span.attributes["agentmesh.cost.unpriced"] is True


def test_agent_and_tool_spans() -> None:
    kit, exporter = _kit()
    with kit.agent("planner", "c"):
        with kit.tool("search"):
            pass
    names = {s.name for s in exporter.get_finished_spans()}
    assert "invoke_agent planner" in names
    assert "execute_tool search" in names
