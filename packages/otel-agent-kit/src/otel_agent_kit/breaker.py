"""Per-edge circuit breaker (closed/open/half-open) with a process-global registry."""

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class BreakerConfig:
    failure_threshold: int = 5
    reset_timeout_sec: float = 30.0
    half_open_max: int = 1


@dataclass
class _EdgeState:
    state: str = CLOSED
    failures: int = 0
    opened_at: float = 0.0
    half_open_calls: int = 0


class EdgeBreakerRegistry:
    """Thread-safe collection of independent per-edge breakers."""

    def __init__(
        self, config: BreakerConfig | None = None, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.config = config or BreakerConfig()
        self._clock = clock
        self._edges: dict[str, _EdgeState] = {}
        self._lock = threading.Lock()

    def _edge(self, edge: str) -> _EdgeState:
        state = self._edges.get(edge)
        if state is None:
            state = _EdgeState()
            self._edges[edge] = state
        return state

    def allow(self, edge: str) -> bool:
        with self._lock:
            state = self._edge(edge)
            if state.state == CLOSED:
                return True
            if state.state == OPEN:
                if self._clock() - state.opened_at >= self.config.reset_timeout_sec:
                    state.state = HALF_OPEN
                    state.half_open_calls = 1
                    return True
                return False
            if state.half_open_calls < self.config.half_open_max:
                state.half_open_calls += 1
                return True
            return False

    def record_success(self, edge: str) -> None:
        with self._lock:
            state = self._edge(edge)
            state.state = CLOSED
            state.failures = 0
            state.half_open_calls = 0

    def record_failure(self, edge: str) -> None:
        with self._lock:
            state = self._edge(edge)
            if state.state == HALF_OPEN:
                self._open(state)
                return
            state.failures += 1
            if state.failures >= self.config.failure_threshold:
                self._open(state)

    def trip(self, edge: str) -> None:
        with self._lock:
            self._open(self._edge(edge))

    def reset(self, edge: str) -> None:
        with self._lock:
            state = self._edge(edge)
            state.state = CLOSED
            state.failures = 0
            state.half_open_calls = 0

    def state_of(self, edge: str) -> str:
        with self._lock:
            return self._edge(edge).state

    def _open(self, state: _EdgeState) -> None:
        state.state = OPEN
        state.opened_at = self._clock()
        state.half_open_calls = 0


def edge_key(src: str, target: str) -> str:
    return f"{src} -> {target}"


def _default_config() -> BreakerConfig:
    return BreakerConfig(
        failure_threshold=int(os.environ.get("OAK_BREAKER_FAILURE_THRESHOLD", "5")),
        reset_timeout_sec=float(os.environ.get("OAK_BREAKER_TTL_SEC", "30")),
    )


_REGISTRY = EdgeBreakerRegistry(_default_config())


def get_registry() -> EdgeBreakerRegistry:
    return _REGISTRY
