"""Polling orchestration only: detection emits signals, it never enforces."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from .budget import BudgetChecker
from .config import WatcherConfig
from .cycle import find_cycles
from .signals import OTLPSignalEmitter, Signal, SignalEmitter
from .signoz_client import (
    ClickHouseClient,
    SigNozClient,
    TimeRange,
    taint_blast_query,
    velocity_query,
    xconv_velocity_query,
)
from .xconv_cycle import find_directed_cycles

logger = logging.getLogger(__name__)


class _Client(Protocol):
    def run_builder_query(
        self, query: dict[str, Any], time_range: TimeRange
    ) -> list[dict[str, Any]]: ...

    def get_trace(self, trace_id: str, time_range: TimeRange) -> list[dict[str, Any]]: ...


def _now_ms(clock: Callable[[], float]) -> int:
    return int(clock() * 1000)


def _attr(span: dict[str, Any], key: str) -> Any:
    value = span.get(key)
    if value is None:
        attrs = span.get("attributes", {})
        if isinstance(attrs, dict):
            value = attrs.get(key)
    return value


def _service_of(span: dict[str, Any]) -> str | None:
    resource = span.get("resource", {})
    if isinstance(resource, dict) and isinstance(resource.get("service.name"), str):
        return resource["service.name"]
    for key in ("service.name", "serviceName"):
        value = _attr(span, key)
        if isinstance(value, str):
            return value
    return None


def _conversation_id(spans: list[dict[str, Any]]) -> str | None:
    for span in spans:
        value = _attr(span, "gen_ai.conversation.id")
        if isinstance(value, str) and value:
            return value
    return None


def _repeated_state(spans: list[dict[str, Any]], services: set[str]) -> bool:
    """True if any cyclic agent emitted the same state hash twice (no progress)."""

    seen: dict[str, set[str]] = {}
    for span in spans:
        service = _service_of(span)
        if service not in services:
            continue
        state = _attr(span, "agentmesh.state.hash")
        if not isinstance(state, str) or not state:
            continue
        bucket = seen.setdefault(service, set())
        if state in bucket:
            return True
        bucket.add(state)
    return False


class LoopWatcher:
    def __init__(
        self,
        client: _Client,
        config: WatcherConfig,
        emitter: SignalEmitter,
        *,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.config = config
        self.emitter = emitter
        self.clock = clock
        self.sleeper = sleeper
        self._sent_at: dict[tuple[str, str], float] = {}
        self.budget = BudgetChecker(client, config.budget_usd)

    def _suppressed(self, key: tuple[str, str]) -> bool:
        now = self.clock()
        sent_at = self._sent_at.get(key)
        if sent_at is not None and now - sent_at < self.config.signal_cooldown_sec:
            return True
        self._sent_at[key] = now
        return False

    def _emit(self, key: tuple[str, str], signal: Signal) -> None:
        if not self._suppressed(key):
            self.emitter.emit(signal)

    def poll_once(self) -> None:
        end_ms = _now_ms(self.clock)
        window = TimeRange(end_ms - self.config.loop_window_sec * 1000, end_ms)
        seen_traces: dict[str, list[dict[str, Any]]] = {}
        # Cross-trace per-edge hop totals feed the circuit breaker: a hot edge (a
        # runaway or poisoned hop reused across traces) is tripped independent of the
        # per-trace loop check below.
        edge_totals: dict[str, int] = {}
        edge_trace: dict[str, str] = {}
        for row in self.client.run_builder_query(velocity_query(), window):
            trace_id = row.get("trace_id")
            src, target = row.get("agentmesh.src"), row.get("peer.service")
            try:
                hops = int(row.get("hop_count", 0))
            except (TypeError, ValueError):
                continue
            if not all(isinstance(value, str) for value in (trace_id, src, target)):
                continue
            edge_label = f"{src} -> {target}"
            edge_totals[edge_label] = edge_totals.get(edge_label, 0) + hops
            edge_trace[edge_label] = trace_id
            if hops <= self.config.loop_max_repeats:
                continue
            spans = seen_traces.setdefault(trace_id, self.client.get_trace(trace_id, window))
            conversation_id = _conversation_id(spans)
            edge = f"{src} -> {target}"
            matching = [
                cycle
                for cycle in find_cycles(spans, self.config.loop_max_repeats)
                if (src, target) in cycle.edges
            ]
            if not (conversation_id and matching):
                continue
            # A cycle alone is not an incident — a generator/critic loop is often
            # intentional. Only flag runaway loops: no progress (repeated state) or a
            # breached iteration hard cap. Cost-budget breaches fire their own signal.
            cyclic_services = {service for cycle in matching for service in cycle.services}
            if _repeated_state(spans, cyclic_services):
                reason = "repeated_state"
            elif hops > self.config.loop_iteration_hard_cap:
                reason = "iteration_cap"
            else:
                continue
            self._emit(
                (conversation_id, edge),
                Signal(
                    "loop_detected",
                    conversation_id,
                    edge,
                    hops,
                    None,
                    trace_id,
                    datetime.now(UTC),
                    reason=reason,
                ),
            )

        for edge_label, total in edge_totals.items():
            if total > self.config.breaker_edge_max:
                self._emit(
                    (edge_label, "edge_unhealthy"),
                    Signal(
                        "edge_unhealthy",
                        None,
                        edge_label,
                        total,
                        None,
                        edge_trace.get(edge_label),
                        datetime.now(UTC),
                    ),
                )

        self._detect_injection(window)
        self._detect_cross_conversation_loops(window)

        lookback = TimeRange(end_ms - self.config.budget_lookback_sec * 1000, end_ms)
        for conversation_id, trace_id in self.budget.active_conversations(window):
            cost = self.budget.conversation_cost(conversation_id, lookback, trace_id)
            if self.budget.breach(cost.usd):
                self._emit(
                    (conversation_id, "budget"),
                    Signal(
                        "budget_exceeded",
                        conversation_id,
                        None,
                        None,
                        cost.usd,
                        trace_id,
                        datetime.now(UTC),
                    ),
                )

    def _detect_injection(self, window: TimeRange) -> None:
        """Emit one injection_detected signal per (trace, origin) with the blast radius."""

        # trace_id -> {(origin, category): set(services)}
        blasts: dict[str, dict[tuple[str, str], set[str]]] = {}
        for row in self.client.run_builder_query(taint_blast_query(), window):
            trace_id = row.get("trace_id")
            origin = row.get("agentmesh.taint.origin")
            category = row.get("agentmesh.taint.category")
            service = row.get("service.name")
            if not all(isinstance(v, str) and v for v in (trace_id, origin, category, service)):
                continue
            blasts.setdefault(trace_id, {}).setdefault((origin, category), set()).add(service)

        for trace_id, groups in blasts.items():
            for (origin, category), services in groups.items():
                blast = ",".join(sorted(services))
                self._emit(
                    (trace_id, f"injection:{origin}"),
                    Signal(
                        "injection_detected",
                        None,
                        None,
                        None,
                        None,
                        trace_id,
                        datetime.now(UTC),
                        category=category,
                        origin=origin,
                        blast=blast,
                    ),
                )

    def _detect_cross_conversation_loops(self, window: TimeRange) -> None:
        """Flag cycles in the union of edges across conversations (invisible per-trace).

        Each conversation contributes at most one occurrence of an edge, so a cycle
        whose edges each recur across >= xconv_min_repeats conversations is reported.
        """

        edges: list[tuple[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        edge_trace: dict[tuple[str, str], str] = {}
        for row in self.client.run_builder_query(xconv_velocity_query(), window):
            conversation_id = row.get("gen_ai.conversation.id")
            src, target = row.get("agentmesh.src"), row.get("peer.service")
            if not all(isinstance(v, str) and v for v in (conversation_id, src, target)):
                continue
            key = (conversation_id, src, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append((src, target))
            edge_trace[(src, target)] = conversation_id

        for cycle in find_directed_cycles(edges, self.config.xconv_min_repeats):
            src, target = cycle.edges[0]
            edge_label = f"{src} -> {target}"
            self._emit(
                (edge_label, "xconv_loop"),
                Signal(
                    "xconv_loop_detected",
                    None,
                    edge_label,
                    cycle.hops,
                    None,
                    None,
                    datetime.now(UTC),
                ),
            )

    def run_forever(self) -> None:
        while True:
            try:
                self.poll_once()
            except Exception:
                # A transient query failure must not permanently stop detection.
                logger.exception("loop watcher poll failed")
            self.sleeper(self.config.poll_interval_sec)


def main() -> None:
    config = WatcherConfig.from_env()
    client = (
        ClickHouseClient(config.signoz_clickhouse_url)
        if config.signoz_clickhouse_url
        else SigNozClient(config.signoz_url, config.signoz_api_key)
    )
    emitter = OTLPSignalEmitter(config.otlp_endpoint)
    try:
        LoopWatcher(client, config, emitter).run_forever()
    finally:
        client.close()
        emitter.shutdown()


if __name__ == "__main__":
    main()
