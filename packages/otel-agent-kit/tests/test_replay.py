from otel_agent_kit import semconv
from otel_agent_kit.replay import build_steps


def _chat(span_id, parent, service, ts, *, captured=False):
    attrs = {
        semconv.GEN_AI_OPERATION_NAME: semconv.CHAT,
        semconv.GEN_AI_USAGE_INPUT_TOKENS: 10,
        semconv.GEN_AI_USAGE_OUTPUT_TOKENS: 20,
        "agentmesh.cost.direct_usd": 0.0012,
    }
    if captured:
        attrs[semconv.GEN_AI_INPUT_MESSAGES] = '[{"role": "user", "content": "hi"}]'
        attrs[semconv.GEN_AI_OUTPUT_MESSAGES] = '[{"role": "assistant", "content": "yo"}]'
    return {
        "span_id": span_id,
        "parent_span_id": parent,
        "timestamp": ts,
        "name": "chat gpt",
        "serviceName": service,
        "attributes": attrs,
    }


def _invoke(span_id, parent, service, ts):
    return {
        "span_id": span_id,
        "parent_span_id": parent,
        "timestamp": ts,
        "name": f"invoke_agent {service}",
        "serviceName": service,
        "attributes": {
            semconv.GEN_AI_OPERATION_NAME: semconv.INVOKE_AGENT,
            semconv.GEN_AI_CONVERSATION_ID: "c-1",
        },
    }


def _tool(span_id, parent, service, ts):
    return {
        "span_id": span_id,
        "parent_span_id": parent,
        "timestamp": ts,
        "name": "execute_tool search_sources",
        "serviceName": service,
        "attributes": {
            semconv.GEN_AI_OPERATION_NAME: semconv.EXECUTE_TOOL,
            semconv.GEN_AI_TOOL_CALL_ARGUMENTS: "climate 2026",
            semconv.GEN_AI_TOOL_CALL_RESULT: '[{"title": "T"}]',
        },
    }


def test_build_steps_orders_agents_and_attaches_children() -> None:
    spans = [
        _invoke("1", "", "planner", "1"),
        _chat("2", "1", "planner", "2"),
        _invoke("3", "1", "researcher", "3"),
        _chat("4", "3", "researcher", "4"),
        _tool("5", "3", "researcher", "5"),
    ]
    steps = build_steps(spans)
    assert [s.agent for s in steps] == ["planner", "researcher"]
    assert steps[0].input_tokens == 10 and steps[0].direct_cost_usd == 0.0012
    assert steps[1].tools[0].name == "search_sources"
    assert steps[1].tools[0].arguments == "climate 2026"
    assert steps[1].tools[0].result == [{"title": "T"}]


def test_content_decoded_when_captured_absent_when_not() -> None:
    captured = build_steps([_invoke("1", "", "w", "1"), _chat("2", "1", "w", "2", captured=True)])
    assert captured[0].input_messages == [{"role": "user", "content": "hi"}]
    plain = build_steps([_invoke("1", "", "w", "1"), _chat("2", "1", "w", "2", captured=False)])
    assert plain[0].input_messages is None


def test_format_replay_renders_agents_and_marks_uncaptured() -> None:
    from otel_agent_kit.mcp.cli import format_replay

    steps = build_steps(
        [
            _invoke("1", "", "planner", "1"),
            _chat("2", "1", "planner", "2", captured=False),
            _invoke("3", "1", "researcher", "3"),
            _tool("5", "3", "researcher", "5"),
        ]
    )
    out = format_replay("t" * 32, steps)
    assert "[1] planner" in out and "[2] researcher" in out
    assert "tool search_sources" in out
    assert "(not captured)" in out  # planner chat was not captured
