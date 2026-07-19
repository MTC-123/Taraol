import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _rule(name: str) -> dict[str, object]:
    return json.loads((ROOT / "signoz" / "alerts" / f"{name}.json").read_text(encoding="utf-8"))


def _spec(rule: dict[str, object]) -> dict[str, object]:
    condition = rule["condition"]
    query = condition["compositeQuery"]["queries"][0]
    return query["spec"]


def test_loop_rule_is_a_contextual_fast_log_alert() -> None:
    rule = _rule("loop-detected")
    spec = _spec(rule)
    assert rule["alert_type"] == "LOGS_BASED_ALERT"
    assert rule["eval_window"] == "30s"
    assert rule["frequency"] == "10s"
    assert spec["signal"] == "logs"
    assert spec["filter"]["expression"] == "signal = 'loop_detected'"
    assert spec["aggregations"][0]["expression"] == "count()"
    assert spec["groupBy"] == ["conversation_id", "edge", "trace_id"]
    assert rule["notification_settings"]["group_by"] == spec["groupBy"]
    assert "$conversation_id" in rule["description"]
    assert rule["labels"]["amr.enforcement"] == "controller"


def test_budget_rule_targets_controller_and_has_no_secrets() -> None:
    rule = _rule("budget-exceeded")
    serialized = json.dumps(rule).lower()
    spec = _spec(rule)
    assert spec["filter"]["expression"] == "signal = 'budget_exceeded'"
    assert spec["groupBy"] == ["conversation_id", "trace_id"]
    assert rule["condition"]["thresholds"]["spec"][0]["channels"] == ["agentmesh-controller"]
    assert not any(secret in serialized for secret in ("password", "token", "api_key", "secret"))
