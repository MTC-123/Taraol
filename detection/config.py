"""Environment-backed configuration for the independent watcher."""

import os
from dataclasses import dataclass


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(os.environ.get(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class WatcherConfig:
    signoz_url: str
    signoz_api_key: str
    loop_window_sec: int
    loop_max_repeats: int
    budget_usd: float
    poll_interval_sec: int
    budget_lookback_sec: int
    signal_cooldown_sec: int
    otlp_endpoint: str
    signoz_clickhouse_url: str | None = None
    breaker_edge_max: int = 10
    xconv_min_repeats: int = 1
    # A cycle is only a runaway loop when the agent stops progressing (repeated state)
    # or hop count crosses this hard cap; below it, a converging cycle is left alone.
    loop_iteration_hard_cap: int = 12

    @classmethod
    def from_env(cls) -> "WatcherConfig":
        api_key = os.environ.get("SIGNOZ_API_KEY", "").strip()
        clickhouse_url = os.environ.get("SIGNOZ_CLICKHOUSE_URL", "").strip() or None
        if not api_key and not clickhouse_url:
            raise ValueError("set SIGNOZ_API_KEY or SIGNOZ_CLICKHOUSE_URL for the loop watcher")
        return cls(
            signoz_url=os.environ.get("SIGNOZ_URL", "http://localhost:8080").rstrip("/"),
            signoz_api_key=api_key,
            loop_window_sec=_positive_int("AMR_LOOP_WINDOW_SEC", 30),
            loop_max_repeats=_positive_int("AMR_LOOP_MAX_REPEATS", 3),
            budget_usd=_positive_float("AMR_BUDGET_USD", 0.01),
            poll_interval_sec=_positive_int("AMR_POLL_INTERVAL_SEC", 5),
            budget_lookback_sec=_positive_int("AMR_BUDGET_LOOKBACK_SEC", 3600),
            signal_cooldown_sec=_positive_int("AMR_SIGNAL_COOLDOWN_SEC", 60),
            otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
            signoz_clickhouse_url=clickhouse_url,
            breaker_edge_max=_positive_int("AMR_BREAKER_EDGE_MAX", 10),
            xconv_min_repeats=_positive_int("AMR_XCONV_MIN_REPEATS", 1),
            loop_iteration_hard_cap=_positive_int("AMR_LOOP_ITERATION_HARD_CAP", 12),
        )
