"""Per-edge circuit breaker for agent-to-agent hops.

Each directed edge ``"src -> target"`` has an independent breaker with the usual
three states:

* ``closed``    — calls flow; consecutive failures are counted.
* ``open``      — calls are short-circuited (the hop is not dispatched).
* ``half_open`` — after ``reset_timeout_sec`` a limited number of trial calls are
  allowed; a success closes the breaker, a failure re-opens it.

A breaker opens two ways: locally, when the client records ``failure_threshold``
consecutive failures, or externally, when the detection controller trips it in
response to a SigNoz ``edge_unhealthy`` alert (observe → act).  The registry is a
process-global shared by the A2A client (which consults it) and the A2A server's
control endpoints (which trip/reset it), mirroring how pause state is shared.
"""

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
        """Return whether a call on ``edge`` may proceed, advancing state as needed."""

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
            # half_open: admit a bounded number of trial calls.
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
        """Force ``edge`` open (controller-driven enforcement)."""

        with self._lock:
            self._open(self._edge(edge))

    def reset(self, edge: str) -> None:
        """Force ``edge`` closed (manual recovery)."""

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
    """Canonical edge label shared with velocity/alert group-bys."""

    return f"{src} -> {target}"


def _default_config() -> BreakerConfig:
    ttl = float(os.environ.get("AMR_BREAKER_TTL_SEC", "30"))
    threshold = int(os.environ.get("AMR_BREAKER_FAILURE_THRESHOLD", "5"))
    return BreakerConfig(failure_threshold=threshold, reset_timeout_sec=ttl)


_REGISTRY = EdgeBreakerRegistry(_default_config())


def get_registry() -> EdgeBreakerRegistry:
    """Return the process-global registry shared by the A2A client and server."""

    return _REGISTRY
