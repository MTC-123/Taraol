from fastapi.testclient import TestClient
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from amr.a2a import A2AClient, create_app
from amr.genai import chat_span, record_chat_result
from amr.llm import LLMResult


def _tracer(service_name: str) -> tuple[object, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer(service_name), exporter


def test_chat_span_sets_cost_and_marks_unknown_models() -> None:
    tracer, exporter = _tracer("planner")
    with chat_span(tracer, "gpt-4.1-mini") as span:
        record_chat_result(span, LLMResult("ok", 1250, 250, "gpt-4.1-mini", "stop"))
    with chat_span(tracer, "unknown-model") as span:
        record_chat_result(span, LLMResult("ok", 1000, 1000, "unknown-model", "stop"))

    spans = {finished.name: finished for finished in exporter.get_finished_spans()}
    assert spans["chat gpt-4.1-mini"].attributes["agentmesh.cost.direct_usd"] == 0.0009
    unknown = spans["chat unknown-model"]
    assert unknown.attributes["agentmesh.cost.direct_usd"] == 0.0
    assert unknown.attributes["agentmesh.cost.unpriced"] is True


def test_hop_span_equals_callee_subtree_cost() -> None:
    planner_tracer, planner_exporter = _tracer("planner")
    researcher_tracer, researcher_exporter = _tracer("researcher")
    server = create_app(tracer=researcher_tracer)

    def research(_: dict[str, object]) -> dict[str, object]:
        with chat_span(researcher_tracer, "gpt-4.1-mini") as span:
            record_chat_result(span, LLMResult("sources", 1000, 500, "gpt-4.1-mini", "stop"))
        return {"agent": "researcher"}

    server.register("work", research)
    with TestClient(server.app) as http_client:
        result = A2AClient(
            "planner", "researcher", tracer=planner_tracer, http_client=http_client
        ).call("work", {}, "http://testserver/a2a")

    # The result metadata is the cross-process handoff; 1000 input + 500 output
    # costs $0.0012 at the configured gpt-4.1-mini rate.
    assert result["_meta"] == {"cost_usd": 0.0012}
    chat = next(
        span for span in researcher_exporter.get_finished_spans() if span.name.startswith("chat")
    )
    hop = next(span for span in planner_exporter.get_finished_spans() if span.name == "a2a.call")
    assert chat.attributes["agentmesh.cost.direct_usd"] == 0.0012
    # The hop carries the callee subtree as downstream cost, distinct from direct cost.
    assert (
        hop.attributes["agentmesh.cost.downstream_usd"]
        == chat.attributes["agentmesh.cost.direct_usd"]
    )
    assert hop.attributes["agentmesh.src"] == "planner"
    assert hop.attributes["peer.service"] == "researcher"


def test_hop_span_includes_a_downstream_callee_subtree_once() -> None:
    planner_tracer, planner_exporter = _tracer("planner")
    researcher_tracer, _ = _tracer("researcher")
    writer_tracer, _ = _tracer("writer")
    writer = create_app(tracer=writer_tracer)
    researcher = create_app(tracer=researcher_tracer)

    def write(_: dict[str, object]) -> dict[str, object]:
        with chat_span(writer_tracer, "gpt-4.1-mini") as span:
            record_chat_result(span, LLMResult("draft", 1000, 500, "gpt-4.1-mini", "stop"))
        return {"agent": "writer"}

    writer.register("work", write)
    with TestClient(writer.app) as writer_http:

        def research(_: dict[str, object]) -> dict[str, object]:
            with chat_span(researcher_tracer, "gpt-4.1-mini") as span:
                record_chat_result(span, LLMResult("sources", 1000, 500, "gpt-4.1-mini", "stop"))
            A2AClient(
                "researcher", "writer", tracer=researcher_tracer, http_client=writer_http
            ).call("work", {}, "http://writer/a2a")
            return {"agent": "researcher"}

        researcher.register("work", research)
        with TestClient(researcher.app) as researcher_http:
            result = A2AClient(
                "planner", "researcher", tracer=planner_tracer, http_client=researcher_http
            ).call("work", {}, "http://researcher/a2a")

    # researcher ($0.0012) + writer ($0.0012), returned only once to planner.
    assert result["_meta"] == {"cost_usd": 0.0024}
    planner_hop = next(
        span for span in planner_exporter.get_finished_spans() if span.name == "a2a.call"
    )
    assert planner_hop.attributes["agentmesh.cost.downstream_usd"] == 0.0024
