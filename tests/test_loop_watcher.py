from typing import Any

from detection.config import WatcherConfig
from detection.loop_watcher import LoopWatcher
from detection.signals import RecordingEmitter
from detection.signoz_client import TimeRange

TRACE_ID = "a" * 32


def _config() -> WatcherConfig:
    return WatcherConfig("http://signoz", "key", 30, 3, 0.01, 5, 3600, 60, "http://ingester:4317")


class FakeClient:
    def __init__(
        self,
        *,
        looping: bool = True,
        cost: float = 0.02,
        tainted: bool = False,
        xconv_split: bool = False,
        progressing: bool = False,
    ) -> None:
        self.looping = looping
        self.cost = cost
        self.tainted = tainted
        self.xconv_split = xconv_split
        self.progressing = progressing

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
        if name == "xconv_velocity":
            if not self.xconv_split:
                return []
            # A benign-per-conversation split loop: writer->critic in one, critic->writer
            # in another. No single trace is cyclic; their union is.
            return [
                {
                    "gen_ai.conversation.id": "cA",
                    "agentmesh.src": "writer",
                    "peer.service": "critic",
                    "hop_count": 1,
                },
                {
                    "gen_ai.conversation.id": "cB",
                    "agentmesh.src": "critic",
                    "peer.service": "writer",
                    "hop_count": 1,
                },
            ]
        if name == "taint_blast":
            if not self.tainted:
                return []
            return [
                {
                    "trace_id": TRACE_ID,
                    "agentmesh.taint.origin": "planner",
                    "agentmesh.taint.category": "jailbreak",
                    "service.name": service,
                }
                for service in ("planner", "researcher", "writer")
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

        def state_hash(service: str, index: int) -> str:
            # progressing=True -> a fresh hash each iteration (healthy convergence);
            # otherwise the agent is stuck on one repeated state (runaway).
            return f"{service}-{index}" if self.progressing else f"stuck-{service}"

        spans: list[dict[str, Any]] = []
        for index, service in enumerate(services):
            attributes: dict[str, Any] = {}
            if index == 0:
                attributes["gen_ai.conversation.id"] = "c-1"
            if service in {"writer", "critic"}:
                attributes["agentmesh.state.hash"] = state_hash(service, index)
            spans.append(
                {
                    "span_id": str(index),
                    "parent_span_id": "" if index == 0 else str(index - 1),
                    "resource": {"service.name": service},
                    "attributes": attributes,
                }
            )
        return spans


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


def test_runaway_loop_signal_carries_repeated_state_reason() -> None:
    emitter = RecordingEmitter()
    watcher = LoopWatcher(FakeClient(cost=0.001), _config(), emitter, clock=lambda: 100.0)
    watcher.poll_once()
    loops = [s for s in emitter.signals if s.signal == "loop_detected"]
    assert len(loops) == 1
    assert loops[0].reason == "repeated_state"


def test_healthy_converging_cycle_is_not_flagged() -> None:
    # A generator/critic cycle whose state changes every iteration is legitimate
    # refinement, not a runaway loop — it must not fire loop_detected.
    emitter = RecordingEmitter()
    watcher = LoopWatcher(
        FakeClient(cost=0.001, progressing=True), _config(), emitter, clock=lambda: 100.0
    )
    watcher.poll_once()
    assert not any(s.signal == "loop_detected" for s in emitter.signals)


def test_watcher_does_not_emit_loop_for_acyclic_trace() -> None:
    emitter = RecordingEmitter()
    watcher = LoopWatcher(
        FakeClient(looping=False, cost=0.001), _config(), emitter, clock=lambda: 100.0
    )
    watcher.poll_once()
    assert emitter.signals == []


def test_watcher_emits_cross_conversation_loop_not_visible_per_trace() -> None:
    now = [100.0]
    emitter = RecordingEmitter()
    watcher = LoopWatcher(
        FakeClient(looping=False, cost=0.001, xconv_split=True),
        _config(),
        emitter,
        clock=lambda: now[0],
    )
    watcher.poll_once()
    watcher.poll_once()  # deduped within cooldown
    xconv = [s for s in emitter.signals if s.signal == "xconv_loop_detected"]
    assert len(xconv) == 1
    assert xconv[0].edge in {"critic -> writer", "writer -> critic"}
    # No per-trace loop fired: each conversation alone is acyclic.
    assert not any(s.signal == "loop_detected" for s in emitter.signals)


def test_watcher_emits_injection_with_blast_radius_once() -> None:
    now = [100.0]
    emitter = RecordingEmitter()
    watcher = LoopWatcher(
        FakeClient(looping=False, cost=0.001, tainted=True),
        _config(),
        emitter,
        clock=lambda: now[0],
    )
    watcher.poll_once()
    watcher.poll_once()  # deduped within cooldown
    injections = [s for s in emitter.signals if s.signal == "injection_detected"]
    assert len(injections) == 1
    signal = injections[0]
    assert signal.category == "jailbreak"
    assert signal.origin == "planner"
    assert signal.blast == "planner,researcher,writer"
    assert signal.trace_id == TRACE_ID
