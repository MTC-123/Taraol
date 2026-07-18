"""Conversation cost queries that count direct chat spans exactly once."""

from dataclasses import dataclass
from typing import Any, Protocol

from .signoz_client import TimeRange, active_conversations_query, conversation_cost_query


class _QueryClient(Protocol):
    def run_builder_query(
        self, query: dict[str, Any], time_range: TimeRange
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class ConversationCost:
    conversation_id: str
    usd: float
    trace_id: str | None


class BudgetChecker:
    def __init__(self, client: _QueryClient, budget_usd: float) -> None:
        self.client = client
        self.budget_usd = budget_usd

    def active_conversations(self, time_range: TimeRange) -> list[tuple[str, str | None]]:
        active: dict[str, str | None] = {}
        for row in self.client.run_builder_query(active_conversations_query(), time_range):
            conversation_id = row.get("gen_ai.conversation.id")
            if isinstance(conversation_id, str) and conversation_id:
                trace_id = row.get("trace_id")
                active.setdefault(conversation_id, trace_id if isinstance(trace_id, str) else None)
        return list(active.items())

    def conversation_cost(
        self, conversation_id: str, time_range: TimeRange, trace_id: str | None
    ) -> ConversationCost:
        rows = self.client.run_builder_query(conversation_cost_query(conversation_id), time_range)
        value = rows[0].get("cost_usd", 0.0) if rows else 0.0
        try:
            usd = float(value)
        except (TypeError, ValueError):
            usd = 0.0
        return ConversationCost(conversation_id, usd, trace_id)

    def breach(self, usd: float) -> bool:
        return usd > self.budget_usd
