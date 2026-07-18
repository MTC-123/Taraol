from typing import Any

from detection.config import WatcherConfig
from detection.loop_watcher import LoopWatcher
from detection.signals import RecordingEmitter
from detection.signoz_client import TimeRange

TRACE_ID = "a" * 32


def _config() -> WatcherConfig:
    return WatcherConfig("http://signoz", "key", 30, 3, 0.01, 5, 3600, 60, "http://ingester:4317")


class FakeClient:
    def __init__(self, *, looping: bool = True, cost: float = 0.02) -> None:
        self.looping = looping
        self.cost = cost

    def run_builder_query(self, query: dict[str, Any], _: TimeRange) -> list[dict[str, Any]]:
        name = query["spec"]["name"]
        if name == "velocity":
            return [
                {
                    "trace_id": TRACE_ID,
                    "agentmesh.src": "critic",
                    "peer.service": "writer",
                    "hop_count": 4,
                }
            ]
        if name == "active_conversations":
            return [{"gen_ai.conversation.id": "c-1", "trace_id": TRACE_ID}]
        if name == "conversation_cost":
            return [{"cost_usd": self.cost}]
        raise AssertionError(name)

    def get_trace(self, _: str, __: TimeRange) -> list[dict[str, Any]]:
        services = ["planner", "writer", "critic", "writer", "critic", "writer", "critic"]
        if not self.looping:
            services = ["planner", "researcher", "writer", "critic"]
        return [
            {
                "span_id": str(index),
                "parent_span_id": "" if index == 0 else str(index - 1),
                "resource": {"service.name": service},
                "attributes": {"gen_ai.conversation.id": "c-1"} if index == 0 else {},
            }
            for index, service in enumerate(services)
        ]


def test_watcher_emits_confirmed_loop_and_budget_once_then_deduplicates() -> None:
    now = [100.0]
    emitter = RecordingEmitter()
    watcher = LoopWatcher(FakeClient(), _config(), emitter, clock=lambda: now[0])
    watcher.poll_once()
    watcher.poll_once()
    assert [signal.signal for signal in emitter.signals] == ["loop_detected", "budget_exceeded"]
    now[0] += 61
    watcher.poll_once()
    assert [signal.signal for signal in emitter.signals].count("loop_detected") == 2


def test_watcher_does_not_emit_loop_for_acyclic_trace() -> None:
    emitter = RecordingEmitter()
    watcher = LoopWatcher(
        FakeClient(looping=False, cost=0.001), _config(), emitter, clock=lambda: 100.0
    )
    watcher.poll_once()
    assert emitter.signals == []
