from datetime import UTC, datetime

from taraol import experiment_report as er
from taraol.detection import loop_watcher as lw
from taraol.detection.signals import Signal
from taraol.detection.signoz_client import (
    ClickHouseClient,
    TimeRange,
    experiment_loop_count_query,
    experiment_run_count_query,
    experiment_span_metrics_query,
)
from taraol.experiments import HealthScore

_ROWS = {
    "experiment_span_metrics": [
        {
            "experiment.variant": "baseline",
            "cost_usd": 0.012,
            "output_tokens": 1200,
            "agent_count": 5,
        },
        {
            "experiment.variant": "runaway",
            "cost_usd": 0.048,
            "output_tokens": 4800,
            "agent_count": 5,
        },
    ],
    "experiment_loop_count": [{"experiment_variant": "runaway", "loops": 6}],
    "experiment_breaker_count": [{"experiment_variant": "runaway", "breaker_trips": 2}],
    "experiment_run_count": [
        {"experiment.variant": "baseline", "runs": 1, "avg_duration_ms": 1800},
        {"experiment.variant": "runaway", "runs": 1, "avg_duration_ms": 5200},
    ],
    "experiment_failure_count": [{"experiment.variant": "runaway", "failures": 1}],
}


class _FakeClient:
    def __init__(self, rows: dict) -> None:
        self._rows = rows

    def run_builder_query(self, query: dict, window: TimeRange) -> list[dict]:
        return self._rows.get(query["spec"]["name"], [])

    def close(self) -> None:
        return None


def test_signal_emits_experiment_and_breaker_keys() -> None:
    signal = Signal(
        "edge_unhealthy",
        None,
        "a -> b",
        30,
        None,
        "trace",
        datetime.now(UTC),
        breaker_reason="loop",
        experiment_id="e",
        experiment_variant="runaway",
        experiment_run_id="r",
    )
    attrs = signal.attributes()
    assert attrs["experiment_id"] == "e"
    assert attrs["experiment_variant"] == "runaway"
    assert attrs["experiment_run_id"] == "r"
    assert attrs["breaker_reason"] == "loop"


def test_signal_without_experiment_omits_keys() -> None:
    signal = Signal(
        "loop_detected", "c", "a -> b", 9, None, "t", datetime.now(UTC), reason="iteration_cap"
    )
    attrs = signal.attributes()
    for key in ("experiment_id", "experiment_variant", "experiment_run_id", "breaker_reason"):
        assert key not in attrs


def test_watcher_reads_experiment_tags_from_spans() -> None:
    spans = [
        {
            "attributes": {
                "experiment.id": "e",
                "experiment.variant": "runaway",
                "experiment.run_id": "r",
            }
        }
    ]
    assert lw._experiment_id(spans) == "e"
    assert lw._experiment_variant(spans) == "runaway"
    assert lw._experiment_run_id(spans) == "r"
    assert lw._experiment_variant([{"attributes": {}}]) is None


def test_clickhouse_experiment_sql_injects_ids() -> None:
    ch = ClickHouseClient("http://ch")
    query = experiment_span_metrics_query("battery", "run9")
    sql = ch._sql("experiment_span_metrics", query["spec"], TimeRange(0, 1000))
    assert "battery" in sql and "run9" in sql
    no_ids = experiment_loop_count_query()
    sql2 = ch._sql("experiment_loop_count", no_ids["spec"], TimeRange(0, 1000))
    assert "loop_detected" in sql2 and "battery" not in sql2


def test_collect_metrics_folds_all_five_queries() -> None:
    metrics = er.collect_metrics(_FakeClient(_ROWS), TimeRange(0, 1), "battery", None)
    runaway = metrics["runaway"]
    assert runaway.loops == 6
    assert runaway.breaker_trips == 2
    assert runaway.failures == 1
    assert runaway.avg_latency_ms == 5200
    assert metrics["baseline"].cost_usd == 0.012
    assert metrics["baseline"].agent_count == 5


def test_summary_reports_highest_health_not_winner() -> None:
    metrics = er.collect_metrics(_FakeClient(_ROWS), TimeRange(0, 1), "battery", None)
    scorer = HealthScore()
    out = er.format_summary("battery", None, metrics, scorer)
    assert "Highest Operational Health: baseline" in out
    assert "winner" not in out.lower()
    assert metrics["baseline"].health(scorer) > metrics["runaway"].health(scorer)


def test_log_queries_use_nanosecond_time_bound() -> None:
    # Regression: signoz_logs.distributed_logs_v2.timestamp is a raw UInt64 of nanoseconds,
    # not a DateTime64 like the traces table. Comparing it to now64(9) matches zero rows, so
    # the log-table experiment queries must bound the window in nanoseconds — otherwise the
    # summary shows avg_latency/loops/breakers/failures all as 0.
    ch = ClickHouseClient("http://clickhouse.invalid")
    window = TimeRange(0, 1)
    for name, query in (
        ("experiment_loop_count", experiment_loop_count_query("e")),
        ("experiment_run_count", experiment_run_count_query("e")),
    ):
        assert "toUnixTimestamp64Nano" in ch._sql(name, query, window)
    # the traces table keeps the DateTime64 (now64) bound
    span_sql = ch._sql("experiment_span_metrics", experiment_span_metrics_query("e"), window)
    assert "toUnixTimestamp64Nano" not in span_sql and "now64(9)" in span_sql


def test_diff_shows_run_level_deltas() -> None:
    metrics = er.collect_metrics(_FakeClient(_ROWS), TimeRange(0, 1), "battery", None)
    baseline_only = er.aggregate({"baseline": metrics["baseline"]})
    both = er.aggregate(metrics)
    out = er.format_diff("run-a", "run-b", baseline_only, both)
    assert "Loops" in out and "-> 6" in out
    assert "Breaker trips" in out
    assert "Cost" in out
