from amr import semconv
from amr.explain import explain_trace


def test_explain_trace_reports_only_trace_grounded_loop_facts() -> None:
    rows = [
        {"span_id": "1", "parent_span_id": "", "name": "a2a.handle", "serviceName": "planner"},
        {"span_id": "2", "parent_span_id": "1", "name": "a2a.call", "serviceName": "critic"},
        {
            "span_id": "3",
            "parent_span_id": "2",
            "name": "chat",
            "serviceName": "writer",
            "attributes": {"gen_ai.operation.name": "chat", "agentmesh.cost.usd": 0.0012},
        },
        {"span_id": "4", "parent_span_id": "3", "name": "a2a.call", "serviceName": "writer"},
        {
            "span_id": "5",
            "parent_span_id": "4",
            "name": "chat",
            "serviceName": "critic",
            "attributes": {"gen_ai.operation.name": "chat", "agentmesh.cost.usd": 0.0023},
        },
        {"span_id": "6", "parent_span_id": "5", "name": "a2a.call", "serviceName": "critic"},
        {"span_id": "7", "parent_span_id": "6", "name": "a2a.handle", "serviceName": "writer"},
    ]
    audit = {"body": "agent_paused", "agent": "writer", "reason": "loop-detected"}
    facts = explain_trace("a" * 32, rows, [audit])
    assert facts["trace_id"] == "a" * 32
    assert facts["cyclic_agents"] == ["critic", "writer"]
    assert facts["hop_count"] == 3
    assert facts["direct_chat_cost_usd"] == 0.0035
    assert facts["pause_action"] == audit
    # No output was flagged in this trace.
    assert facts["bad_output_origin"] is None


def test_explain_trace_surfaces_bad_output_origin() -> None:
    rows = [
        {"span_id": "1", "parent_span_id": "", "name": "invoke_agent", "serviceName": "planner"},
        {
            "span_id": "2",
            "parent_span_id": "1",
            "name": "invoke_agent",
            "serviceName": "writer",
            "attributes": {
                semconv.AGENTMESH_OUTPUT_FLAGGED: True,
                semconv.AGENTMESH_OUTPUT_CATEGORY: "hallucination",
            },
        },
        {"span_id": "3", "parent_span_id": "2", "name": "invoke_agent", "serviceName": "critic"},
    ]
    facts = explain_trace("b" * 32, rows)
    assert facts["bad_output_origin"] == {
        "origin": "writer",
        "category": "hallucination",
        "consumers": ["critic"],
    }
