from typing import Any

from detection.budget import BudgetChecker
from detection.signoz_client import TimeRange


class FakeClient:
    def __init__(self, cost: float) -> None:
        self.cost = cost

    def run_builder_query(self, query: dict[str, Any], _: TimeRange) -> list[dict[str, Any]]:
        name = query["spec"]["name"]
        if name == "active_conversations":
            return [{"gen_ai.conversation.id": "c-1", "trace_id": "a" * 32}]
        return [{"cost_usd": self.cost}]


def test_budget_checker_handles_under_equal_and_over_threshold() -> None:
    window = TimeRange(0, 1)
    under = BudgetChecker(FakeClient(0.009), 0.01)
    equal = BudgetChecker(FakeClient(0.01), 0.01)
    over = BudgetChecker(FakeClient(0.011), 0.01)
    assert under.active_conversations(window) == [("c-1", "a" * 32)]
    assert not under.breach(under.conversation_cost("c-1", window, None).usd)
    assert not equal.breach(equal.conversation_cost("c-1", window, None).usd)
    assert over.breach(over.conversation_cost("c-1", window, None).usd)
