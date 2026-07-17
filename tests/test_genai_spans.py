from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from amr import semconv
from amr.genai import agent_span, chat_span, record_chat_result, tool_span
from amr.llm import complete


def test_genai_helpers_emit_pinned_attributes_without_content() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "planner"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("planner")

    with agent_span(tracer, "planner", "conversation-1"):
        with chat_span(tracer, "example-small") as span:
            record_chat_result(span, complete("make a plan", "example-small"))
        with tool_span(tracer, "search_sources"):
            pass

    spans = {span.name: span for span in exporter.get_finished_spans()}
    chat = spans["chat example-small"]
    assert chat.attributes[semconv.GEN_AI_OPERATION_NAME] == semconv.CHAT
    assert chat.attributes[semconv.GEN_AI_REQUEST_MODEL] == "example-small"
    assert chat.attributes[semconv.GEN_AI_USAGE_INPUT_TOKENS] > 0
    assert chat.attributes[semconv.GEN_AI_USAGE_OUTPUT_TOKENS] > 0
    assert "gen_ai.prompt" not in chat.attributes
    assert spans["execute_tool search_sources"].attributes[semconv.GEN_AI_OPERATION_NAME] == (
        semconv.EXECUTE_TOOL
    )
    agent = spans["invoke_agent planner"]
    assert agent.attributes[semconv.GEN_AI_CONVERSATION_ID] == "conversation-1"
