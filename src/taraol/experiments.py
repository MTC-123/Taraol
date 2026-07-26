"""AgentLab — compare the *operational* behavior of agent-workload variants.

Tag every span (and detection signal) in a run with ``experiment.id`` / ``experiment.variant``
/ ``experiment.run_id``, fire the same workload once per variant, then compare cost, latency,
loop count, breaker trips, and failures in a SigNoz dashboard + the ``experiment`` CLI —
**SigNoz is the dashboard.** Unlike answer-quality eval, AgentLab compares how the system
*behaves*: which variant is cheaper, faster, and safer to run.

Hierarchy (matters once you run more than once)::

    Experiment  ->  Run (one .run(), shared run_id)  ->  Variant  ->  Trace

Primary API is the fluent builder::

    from taraol import Experiment

    (Experiment("market-report", description="Gemini prompt A/B", author="Fraol")
        .variant("baseline", loop_mode="off")
        .variant("runaway",  loop_mode="storm")
        .run(workload))            # workload(variant) is called once per variant

Variant knobs (model / loop_mode / temperature / prompt) are plain keywords, read back as
``variant.loop_mode``. Knob *values* are treated as content: the ``experiment_run`` log carries
them only when the process opted into content capture (knob names are always logged). Never
put secrets in knobs.
"""

import functools
import platform
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import _logs

from . import semconv
from .facade import ExperimentContext, current_experiment, use_experiment

_EXPERIMENT_LOGGER = "agentmesh.experiment"
_CONFIG_VALUE_MAX = 500  # experiment knobs are short; cap defensively so a stray prompt can't dump


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001 — best-effort metadata probe; never fail the run
        return None


def _kit_version() -> str | None:
    try:
        from taraol import __version__

        return __version__
    except Exception:  # noqa: BLE001 — best-effort metadata probe; never fail the run
        return None


@dataclass(frozen=True, slots=True)
class ExperimentMetadata:
    """Reproducibility record: who/what/when produced a run, filled in automatically."""

    description: str | None = None
    author: str | None = None
    commit: str | None = None
    python_version: str | None = None
    kit_version: str | None = None

    @classmethod
    def collect(
        cls, *, description: str | None = None, author: str | None = None
    ) -> "ExperimentMetadata":
        return cls(
            description=description,
            author=author,
            commit=_git_commit(),
            python_version=platform.python_version(),
            kit_version=_kit_version(),
        )

    def span_tags(self) -> dict[str, str]:
        """Lean, high-value tags stamped on *every* span in the run (grouping + repro)."""

        return {semconv.EXPERIMENT_COMMIT: self.commit} if self.commit else {}

    def log_attributes(self) -> dict[str, str]:
        """Full reproducibility record for the once-per-variant ``experiment_run`` log."""

        pairs = {
            semconv.EXPERIMENT_DESCRIPTION: self.description,
            semconv.EXPERIMENT_AUTHOR: self.author,
            semconv.EXPERIMENT_COMMIT: self.commit,
            semconv.EXPERIMENT_PYTHON: self.python_version,
            semconv.EXPERIMENT_KIT_VERSION: self.kit_version,
        }
        return {k: v for k, v in pairs.items() if v}


@dataclass(frozen=True, slots=True)
class Variant:
    """One arm of an experiment: a name + a bag of knobs the workload reads.

    Config knobs read as attributes too: ``variant.style`` == ``variant.config["style"]``.
    """

    name: str
    config: Mapping[str, Any] = field(default_factory=dict)

    def __getattr__(self, key: str) -> Any:
        # Only called for names that aren't real fields; delegate to the config bag.
        try:
            return self.config[key]
        except KeyError:
            raise AttributeError(f"variant {self.name!r} has no config knob {key!r}") from None


@dataclass(frozen=True, slots=True)
class HealthScore:
    """Pluggable operational-health scorer. Higher = healthier to *run*.

    Deliberately **not** a universal "winner": one team optimizes cost, another latency,
    another stability. Tune the weights to what you care about.
    """

    base: float = 100.0
    loop_weight: float = 10.0
    breaker_weight: float = 5.0
    latency_weight: float = 0.2  # per second of P95 latency
    cost_weight: float = 0.1  # per USD
    failure_weight: float = 20.0  # a variant that errored is not a healthy one to run

    def score(
        self,
        *,
        loops: float = 0,
        breaker_trips: float = 0,
        p95_latency_s: float = 0.0,
        cost_usd: float = 0.0,
        failures: float = 0,
    ) -> float:
        return round(
            self.base
            - self.loop_weight * loops
            - self.breaker_weight * breaker_trips
            - self.latency_weight * p95_latency_s
            - self.cost_weight * cost_usd
            - self.failure_weight * failures,
            1,
        )


@dataclass(frozen=True, slots=True)
class VariantResult:
    variant: str
    status: str  # "success" | "failed"
    duration_ms: float
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    experiment_id: str
    run_id: str
    results: list[VariantResult]

    @property
    def ok(self) -> bool:
        return all(r.status == "success" for r in self.results)

    def summary(self, *, since_sec: int = 3600, scorer: "HealthScore | None" = None) -> str:
        """This run's per-variant table from SigNoz (same output as the summary CLI).

        Needs the ``[detection]`` extra and ``SIGNOZ_API_KEY`` or ``SIGNOZ_CLICKHOUSE_URL``
        set. Telemetry is batched — give the collector a few seconds after ``.run()``.
        """

        from .experiment_report import summarize

        return summarize(self.experiment_id, run_id=self.run_id, since_sec=since_sec, scorer=scorer)


def _config_attributes(config: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in config.items():
        if isinstance(value, (str, int, float)):  # bool is an int subclass — covered
            out[f"experiment.config.{key}"] = str(value)[:_CONFIG_VALUE_MAX]
    return out


def _capture_enabled() -> bool:
    """Whether the process opted into content capture (variant knobs may hold prompt text)."""

    try:
        from .facade import get_default_instrument

        return bool(get_default_instrument().settings.capture_content)
    except Exception:  # noqa: BLE001 — no instrument yet counts as opted out
        return False


def _emit_experiment_run(
    experiment_id: str,
    variant: Variant,
    run_id: str,
    status: str,
    duration_ms: float,
    error: str | None,
    metadata: ExperimentMetadata,
) -> None:
    """Emit one content-free ``experiment_run`` log record per variant (status + duration)."""

    attributes: dict[str, Any] = {
        "event": "experiment_run",
        semconv.EXPERIMENT_ID: experiment_id,
        semconv.EXPERIMENT_VARIANT: variant.name,
        semconv.EXPERIMENT_RUN_ID: run_id,
        semconv.EXPERIMENT_STATUS: status,
        semconv.EXPERIMENT_DURATION_MS: duration_ms,
    }
    attributes.update(metadata.log_attributes())
    # Knob VALUES may hold prompt text (e.g. .variant("terse", prompt=...)), so they are
    # content: only logged when the process opted into capture. Names are always safe.
    if variant.config:
        attributes["experiment.config_keys"] = ",".join(sorted(variant.config))
    if _capture_enabled():
        attributes.update(_config_attributes(variant.config))
    if error:
        attributes["experiment.error"] = error[:_CONFIG_VALUE_MAX]
    _logs.get_logger(_EXPERIMENT_LOGGER).emit(
        _logs.LogRecord(  # type: ignore[attr-defined]
            body="experiment_run",
            severity_text="INFO" if status == "success" else "ERROR",
            attributes=attributes,
        )
    )


class Experiment:
    """Fluent builder that fires a workload once per variant under a shared ``run_id``."""

    def __init__(
        self,
        experiment_id: str,
        *,
        description: str | None = None,
        author: str | None = None,
        metadata: ExperimentMetadata | None = None,
    ) -> None:
        self.id = experiment_id
        self._variants: list[Variant] = []
        self.metadata = metadata or ExperimentMetadata.collect(
            description=description, author=author
        )

    def variant(
        self, name: str, config: Mapping[str, Any] | None = None, **knobs: Any
    ) -> "Experiment":
        """Add one arm. Knobs read best as keywords: ``.variant("terse", style="terse")``
        (``config=`` accepts a prebuilt mapping; keywords win on collision)."""

        self._variants.append(Variant(name, {**dict(config or {}), **knobs}))
        return self

    def compare(self, *variants: "Variant | str", **knobs: Any) -> "Experiment":
        """Alias for ``.variant(...)`` that reads as the intent.

        Two forms::

            .compare("terse", prompt="...")     # one arm with its knobs (== .variant)
            .compare(baseline, runaway, "v3")   # several prebuilt arms / bare names
        """

        if knobs:
            if len(variants) != 1 or not isinstance(variants[0], str):
                raise TypeError("compare() with knobs takes exactly one variant name")
            return self.variant(variants[0], **knobs)
        for v in variants:
            if isinstance(v, Variant):
                self._variants.append(v)
            elif isinstance(v, str):
                self._variants.append(Variant(v))
            else:
                raise TypeError("compare() takes Variant objects or variant-name strings")
        return self

    def run(self, workload: Callable[[Variant], Any], *, run_id: str | None = None) -> RunResult:
        """Run ``workload(variant)`` once per variant under one ``run_id``.

        A variant that raises is recorded ``status="failed"`` and the run continues — an
        experiment runner must not abort after a single failure.
        """

        if not self._variants:
            raise ValueError("add at least one .variant(...) before .run()")
        rid = run_id or uuid.uuid4().hex
        span_tags = self.metadata.span_tags()
        results: list[VariantResult] = []
        for variant in self._variants:
            ctx = ExperimentContext(self.id, variant.name, rid, span_tags)
            started = time.monotonic()
            status, error = "success", None
            with use_experiment(ctx):
                try:
                    workload(variant)
                except Exception as exc:  # noqa: BLE001 — capture, don't abort the run
                    status, error = "failed", f"{type(exc).__name__}: {exc}"
            duration_ms = round((time.monotonic() - started) * 1000, 1)
            _emit_experiment_run(self.id, variant, rid, status, duration_ms, error, self.metadata)
            results.append(VariantResult(variant.name, status, duration_ms, error))
        return RunResult(self.id, rid, results)


# --- Decorators (secondary sugar; the builder is the primary API) --------------------
#
# These tag the wrapped function's spans with an experiment context. They do NOT emit an
# experiment_run log record (that is the builder's runner job); the summary CLI still sees
# cost/latency/loops because those come from the tagged spans.


def experiment(
    experiment_id: str,
    *,
    variant: str = "baseline",
    run_id: str | None = None,
    description: str | None = None,
    author: str | None = None,
) -> Callable:
    """Decorator form: run the wrapped fn inside an experiment context."""

    metadata = ExperimentMetadata.collect(description=description, author=author)
    resolved_run = run_id or uuid.uuid4().hex

    def deco(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = ExperimentContext(experiment_id, variant, resolved_run, metadata.span_tags())
            with use_experiment(ctx):
                return f(*args, **kwargs)

        return wrapper

    return deco


def variant(name: str, *, experiment_id: str | None = None, run_id: str | None = None) -> Callable:
    """Decorator form: set the variant, inheriting id/run from the active experiment context."""

    def deco(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            active = current_experiment()
            eid = experiment_id or (active.id if active else None)
            if eid is None:
                raise RuntimeError(
                    "@variant needs an active experiment (use @experiment or pass experiment_id=)"
                )
            rid = run_id or (active.run_id if active else uuid.uuid4().hex)
            meta = dict(active.metadata) if active else {}
            with use_experiment(ExperimentContext(eid, name, rid, meta)):
                return f(*args, **kwargs)

        return wrapper

    return deco
