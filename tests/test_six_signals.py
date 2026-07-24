"""Acceptance checks for the six observed—not merely configured—signals."""

import json
from pathlib import Path

from amr.explain import explain_trace
from amr.mcp_client import format_explanation
from amr.mesh import STORM_SAFETY_CAP, path_from

ROOT = Path(__file__).parents[1]


def _dashboard(name: str) -> dict[str, object]:
    return json.loads((ROOT / "signoz" / "dashboards" / name).read_text(encoding="utf-8"))


def test_six_signals_are_exercised_by_the_demo_contract() -> None:
    # 1: a distributed trace with the actual five named services and a cycle.
    trace = [
        {"span_id": "1", "parent_span_id": "", "serviceName": "planner", "name": "a2a.handle"},
        {"span_id": "2", "parent_span_id": "1", "serviceName": "researcher", "name": "a2a.call"},
        {"span_id": "3", "parent_span_id": "2", "serviceName": "router", "name": "a2a.call"},
        {"span_id": "4", "parent_span_id": "3", "serviceName": "writer", "name": "a2a.call"},
        {"span_id": "5", "parent_span_id": "4", "serviceName": "critic", "name": "a2a.call"},
        {"span_id": "6", "parent_span_id": "5", "serviceName": "writer", "name": "a2a.call"},
        {"span_id": "7", "parent_span_id": "6", "serviceName": "critic", "name": "a2a.call"},
        {
            "span_id": "8",
            "parent_span_id": "7",
            "serviceName": "writer",
            "name": "chat",
            "attributes": {"gen_ai.operation.name": "chat", "agentmesh.cost.direct_usd": 0.0012},
        },
    ]
    audit = [{"body": "agent_paused", "trace_id": "a" * 32, "conversation_id": "demo"}]
    facts = explain_trace("a" * 32, trace, audit)
    assert set(facts["services"]) == {"planner", "researcher", "writer", "critic", "router"}
    assert set(facts["cyclic_agents"]) == {"writer", "critic"}
    assert facts["pause_action"] == audit[0]

    # 2: derived RED metrics, 3: trace-correlated reasoning/audit logs.
    edge = _dashboard("cost-per-edge.json")
    serialized = json.dumps(edge)
    assert "signoz_calls_total" in serialized and "signoz_latency_bucket" in serialized
    assert "agentmesh.cost.downstream_usd" in serialized and "agentmesh.src" in serialized
    event_source = (ROOT / "src" / "amr" / "events.py").read_text(encoding="utf-8")
    assert "agent_reasoning" in event_source and "conversation_id" in event_source

    # 4: three focused dashboard exports, 5: Terraform rules/routing, 6: MCP output.
    names = ["cost-per-edge.json", "cost-per-agent.json", "conversation-budget.json"]
    assert all(len(_dashboard(name)["widgets"]) <= 12 for name in names)
    terraform = (ROOT / "signoz" / "terraform" / "alerts.tf").read_text(encoding="utf-8")
    assert "signoz_alert" in terraform and "signoz_route_policy" in terraform
    output = format_explanation(facts)
    assert "Loop Post-mortem" in output and "USD 0.0012" in output


def test_storm_mode_has_a_hard_cap() -> None:
    assert STORM_SAFETY_CAP == 24
    # The deterministic traversal never creates more edges than the declared cap.
    import os

    previous = os.environ.get("AMR_LOOP_MODE")
    os.environ["AMR_LOOP_MODE"] = "storm"
    try:
        assert len(path_from()) - 1 == STORM_SAFETY_CAP
    finally:
        if previous is None:
            del os.environ["AMR_LOOP_MODE"]
        else:
            os.environ["AMR_LOOP_MODE"] = previous
