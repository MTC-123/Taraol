"""AgentLab summary/diff — aggregate per-variant operational metrics from SigNoz.

Provider abstraction: the SigNoz Query API when ``SIGNOZ_API_KEY`` is set (works on Cloud),
else the direct ClickHouse fallback (works on Community) — the *same* selection the watcher
uses (:func:`taraol.detection.loop_watcher.make_client`). SigNoz is the dashboard;
this is its terminal companion for a quick, scriptable read.

Imports the ``[detection]`` extra, so it is only pulled in lazily by the CLI.
"""

import time
from dataclasses import dataclass

from .detection.config import WatcherConfig
from .detection.loop_watcher import make_client
from .detection.signoz_client import (
    TimeRange,
    experiment_breaker_count_query,
    experiment_failure_count_query,
    experiment_loop_count_query,
    experiment_run_count_query,
    experiment_span_metrics_query,
)
from .experiments import HealthScore


def _num(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


@dataclass
class VariantMetrics:
    """One variant's operational profile — the numbers a developer picks a workflow on."""

    variant: str
    cost_usd: float = 0.0
    output_tokens: int = 0
    agent_count: int = 0
    avg_latency_ms: float = 0.0
    loops: int = 0
    breaker_trips: int = 0
    runs: int = 0
    failures: int = 0

    def health(self, scorer: HealthScore) -> float:
        return scorer.score(
            loops=self.loops,
            breaker_trips=self.breaker_trips,
            p95_latency_s=self.avg_latency_ms / 1000.0,
            cost_usd=self.cost_usd,
        )


def _window(since_sec: int) -> TimeRange:
    end_ms = int(time.time() * 1000)
    return TimeRange(end_ms - since_sec * 1000, end_ms)


def collect_metrics(
    client: object,
    window: TimeRange,
    experiment_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, VariantMetrics]:
    """Run the five per-variant queries and fold them into one profile per variant."""

    metrics: dict[str, VariantMetrics] = {}

    def ensure(variant: str) -> VariantMetrics:
        return metrics.setdefault(variant, VariantMetrics(variant=variant))

    for row in client.run_builder_query(  # type: ignore[attr-defined]
        experiment_span_metrics_query(experiment_id, run_id), window
    ):
        variant = row.get("experiment.variant")
        if not isinstance(variant, str) or not variant:
            continue
        m = ensure(variant)
        m.cost_usd = round(_num(row.get("cost_usd")), 6)
        m.output_tokens = int(_num(row.get("output_tokens")))
        m.agent_count = int(_num(row.get("agent_count")))

    for query, attr in (
        (experiment_loop_count_query, "loops"),
        (experiment_breaker_count_query, "breaker_trips"),
    ):
        for row in client.run_builder_query(query(experiment_id, run_id), window):  # type: ignore[attr-defined]
            variant = row.get("experiment_variant")
            if isinstance(variant, str) and variant:
                setattr(ensure(variant), attr, int(_num(row.get(attr))))

    for row in client.run_builder_query(  # type: ignore[attr-defined]
        experiment_run_count_query(experiment_id, run_id), window
    ):
        variant = row.get("experiment.variant")
        if isinstance(variant, str) and variant:
            m = ensure(variant)
            m.runs = int(_num(row.get("runs")))
            m.avg_latency_ms = round(_num(row.get("avg_duration_ms")), 1)

    for row in client.run_builder_query(  # type: ignore[attr-defined]
        experiment_failure_count_query(experiment_id, run_id), window
    ):
        variant = row.get("experiment.variant")
        if isinstance(variant, str) and variant:
            ensure(variant).failures = int(_num(row.get("failures")))

    return metrics


def aggregate(metrics: dict[str, VariantMetrics]) -> VariantMetrics:
    """Roll a run's variants into one run-level profile (for ``diff``)."""

    agg = VariantMetrics(variant="(run)")
    total_runs = sum(m.runs for m in metrics.values())
    for m in metrics.values():
        agg.cost_usd += m.cost_usd
        agg.output_tokens += m.output_tokens
        agg.loops += m.loops
        agg.breaker_trips += m.breaker_trips
        agg.runs += m.runs
        agg.failures += m.failures
        agg.agent_count = max(agg.agent_count, m.agent_count)
    if total_runs:
        agg.avg_latency_ms = round(
            sum(m.avg_latency_ms * m.runs for m in metrics.values()) / total_runs, 1
        )
    agg.cost_usd = round(agg.cost_usd, 6)
    return agg


_HEADER = (
    f"{'variant':<16}{'cost$':>10}{'tokens':>9}{'agents':>8}"
    f"{'avg ms':>9}{'loops':>7}{'breakers':>10}{'fails':>7}{'health':>8}"
)


def format_summary(
    experiment_id: str,
    run_id: str | None,
    metrics: dict[str, VariantMetrics],
    scorer: HealthScore,
) -> str:
    title = f"AgentLab - {experiment_id}"
    if run_id:
        title += f"  (run {run_id[:12]})"
    lines = [title, _HEADER, "-" * len(_HEADER)]
    if not metrics:
        lines.append("(no experiment telemetry in the window — is the stack up and the run done?)")
        return "\n".join(lines)
    best_variant, best_health = None, float("-inf")
    for variant in sorted(metrics):
        m = metrics[variant]
        health = m.health(scorer)
        if health > best_health:
            best_variant, best_health = variant, health
        lines.append(
            f"{variant:<16}{m.cost_usd:>10.4f}{m.output_tokens:>9d}{m.agent_count:>8d}"
            f"{m.avg_latency_ms:>9.0f}{m.loops:>7d}{m.breaker_trips:>10d}"
            f"{m.failures:>7d}{health:>8.1f}"
        )
    lines.append("")
    lines.append(
        f"Highest Operational Health: {best_variant}  "
        f"(a factual read, not a universal 'best' - tune HealthScore to what you optimize)"
    )
    return "\n".join(lines)


def _pct(a: float, b: float) -> str:
    if a == 0:
        return "-" if b == 0 else "new"
    return f"{(b - a) / a * 100:+.0f}%"


def format_diff(run1: str, run2: str, a: VariantMetrics, b: VariantMetrics) -> str:
    lines = [f"AgentLab diff - run {run1[:12]} -> run {run2[:12]}", ""]
    lines.append(
        f"{'Cost $':<16}{a.cost_usd:>12.4f} -> {b.cost_usd:<12.4f}{_pct(a.cost_usd, b.cost_usd):>8}"
    )
    lines.append(
        f"{'Avg latency ms':<16}{a.avg_latency_ms:>12.0f} -> {b.avg_latency_ms:<12.0f}"
        f"{_pct(a.avg_latency_ms, b.avg_latency_ms):>8}"
    )
    lines.append(
        f"{'Output tokens':<16}{a.output_tokens:>12d} -> {b.output_tokens:<12d}"
        f"{_pct(a.output_tokens, b.output_tokens):>8}"
    )
    lines.append(f"{'Loops':<16}{a.loops:>12d} -> {b.loops:<12d}")
    lines.append(f"{'Breaker trips':<16}{a.breaker_trips:>12d} -> {b.breaker_trips:<12d}")
    lines.append(f"{'Failures':<16}{a.failures:>12d} -> {b.failures:<12d}")
    return "\n".join(lines)


def summarize(
    experiment_id: str,
    *,
    run_id: str | None = None,
    since_sec: int = 3600,
    scorer: HealthScore | None = None,
) -> str:
    config = WatcherConfig.from_env()
    client = make_client(config)
    try:
        metrics = collect_metrics(client, _window(since_sec), experiment_id, run_id)
    finally:
        client.close()  # type: ignore[attr-defined]
    return format_summary(experiment_id, run_id, metrics, scorer or HealthScore())


def diff(run1: str, run2: str, *, since_sec: int = 3600) -> str:
    config = WatcherConfig.from_env()
    client = make_client(config)
    try:
        window = _window(since_sec)
        first = aggregate(collect_metrics(client, window, None, run1))
        second = aggregate(collect_metrics(client, window, None, run2))
    finally:
        client.close()  # type: ignore[attr-defined]
    return format_diff(run1, run2, first, second)
