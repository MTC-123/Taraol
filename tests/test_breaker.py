from amr.breaker import CLOSED, HALF_OPEN, OPEN, BreakerConfig, EdgeBreakerRegistry, edge_key


def _registry(now: list[float]) -> EdgeBreakerRegistry:
    return EdgeBreakerRegistry(
        BreakerConfig(failure_threshold=3, reset_timeout_sec=30.0, half_open_max=1),
        clock=lambda: now[0],
    )


def test_edge_key_is_canonical() -> None:
    assert edge_key("writer", "critic") == "writer -> critic"


def test_closed_edge_allows_calls() -> None:
    now = [0.0]
    registry = _registry(now)
    assert registry.allow("a -> b") is True
    assert registry.state_of("a -> b") == CLOSED


def test_consecutive_failures_open_the_edge() -> None:
    now = [0.0]
    registry = _registry(now)
    edge = "writer -> critic"
    for _ in range(3):
        assert registry.allow(edge) is True
        registry.record_failure(edge)
    assert registry.state_of(edge) == OPEN
    assert registry.allow(edge) is False


def test_open_edge_half_opens_after_timeout_then_closes_on_success() -> None:
    now = [0.0]
    registry = _registry(now)
    edge = "writer -> critic"
    registry.trip(edge)
    assert registry.allow(edge) is False
    now[0] += 31  # past reset_timeout
    assert registry.allow(edge) is True  # single trial call
    assert registry.state_of(edge) == HALF_OPEN
    assert registry.allow(edge) is False  # half_open_max = 1
    registry.record_success(edge)
    assert registry.state_of(edge) == CLOSED
    assert registry.allow(edge) is True


def test_half_open_failure_reopens_the_edge() -> None:
    now = [0.0]
    registry = _registry(now)
    edge = "writer -> critic"
    registry.trip(edge)
    now[0] += 31
    assert registry.allow(edge) is True
    registry.record_failure(edge)
    assert registry.state_of(edge) == OPEN


def test_reset_forces_closed() -> None:
    now = [0.0]
    registry = _registry(now)
    edge = "writer -> critic"
    registry.trip(edge)
    registry.reset(edge)
    assert registry.state_of(edge) == CLOSED


def test_edges_are_independent() -> None:
    now = [0.0]
    registry = _registry(now)
    registry.trip("a -> b")
    assert registry.allow("a -> b") is False
    assert registry.allow("c -> d") is True
