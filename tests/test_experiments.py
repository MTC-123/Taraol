import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from taraol import (
    Experiment,
    ExperimentMetadata,
    HealthScore,
    Variant,
    experiment,
    semconv,
    variant,
)
from taraol.config import Settings
from taraol.cost import CostModel
from taraol.facade import Instrument, set_default_instrument


def _install(**settings_kw: object) -> tuple[Instrument, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "planner"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    settings = Settings(service_name="planner", **settings_kw)  # type: ignore[arg-type]
    kit = Instrument(provider.get_tracer("planner"), settings, CostModel())
    set_default_instrument(kit)
    return kit, exporter


def test_builder_tags_spans_with_one_shared_run_id() -> None:
    kit, exporter = _install()

    def workload(_v: Variant) -> None:
        with kit.agent("planner", "c"):
            pass

    result = Experiment("exp", author="Fraol").variant("a").variant("b").run(workload)

    spans = exporter.get_finished_spans()
    assert {s.attributes[semconv.EXPERIMENT_VARIANT] for s in spans} == {"a", "b"}
    run_ids = {s.attributes[semconv.EXPERIMENT_RUN_ID] for s in spans}
    assert run_ids == {result.run_id}  # one run_id shared across variants
    assert all(s.attributes[semconv.EXPERIMENT_ID] == "exp" for s in spans)


def test_no_experiment_tags_when_not_running() -> None:
    kit, exporter = _install()
    with kit.agent("planner", "c"):
        pass
    span = exporter.get_finished_spans()[0]
    assert semconv.EXPERIMENT_ID not in span.attributes
    assert semconv.EXPERIMENT_VARIANT not in span.attributes


def test_env_settings_tag_spans() -> None:
    kit, exporter = _install(
        experiment_id="e1", experiment_variant="baseline", experiment_run_id="r1"
    )
    with kit.agent("planner", "c"):
        pass
    span = exporter.get_finished_spans()[0]
    assert span.attributes[semconv.EXPERIMENT_ID] == "e1"
    assert span.attributes[semconv.EXPERIMENT_VARIANT] == "baseline"
    assert span.attributes[semconv.EXPERIMENT_RUN_ID] == "r1"


def test_variant_failure_is_captured_and_run_continues() -> None:
    kit, _ = _install()
    seen: list[str] = []

    def workload(v: Variant) -> None:
        seen.append(v.name)
        with kit.agent("a", "c"):
            pass
        if v.name == "boom":
            raise ValueError("kaboom")

    result = Experiment("e").variant("ok").variant("boom").variant("after").run(workload)

    assert seen == ["ok", "boom", "after"]  # one failure did not abort the run
    assert {r.variant: r.status for r in result.results} == {
        "ok": "success",
        "boom": "failed",
        "after": "success",
    }
    assert result.ok is False
    boom = next(r for r in result.results if r.variant == "boom")
    assert boom.error is not None and "kaboom" in boom.error


def test_compare_alias_matches_repeated_variant() -> None:
    _install()
    e = Experiment("e").compare(Variant("a", {"x": 1}), "b")
    assert [v.name for v in e._variants] == ["a", "b"]


def test_run_without_variants_raises() -> None:
    _install()
    with pytest.raises(ValueError, match="variant"):
        Experiment("e").run(lambda _v: None)


def test_experiment_decorator_tags_spans() -> None:
    kit, exporter = _install()

    @experiment("dexp", variant="v1")
    def run_it() -> None:
        with kit.agent("a", "c"):
            pass

    run_it()
    span = exporter.get_finished_spans()[0]
    assert span.attributes[semconv.EXPERIMENT_ID] == "dexp"
    assert span.attributes[semconv.EXPERIMENT_VARIANT] == "v1"
    assert semconv.EXPERIMENT_RUN_ID in span.attributes


def test_variant_decorator_inherits_active_experiment() -> None:
    kit, exporter = _install()

    @experiment("outer", variant="ignored")
    @variant("inner")
    def f() -> None:
        with kit.agent("a", "c"):
            pass

    f()
    span = exporter.get_finished_spans()[0]
    assert span.attributes[semconv.EXPERIMENT_ID] == "outer"
    assert span.attributes[semconv.EXPERIMENT_VARIANT] == "inner"


def test_variant_decorator_without_experiment_raises() -> None:
    _install()

    @variant("v")
    def f() -> int:
        return 1

    with pytest.raises(RuntimeError, match="experiment"):
        f()


def test_health_score_default_and_custom_weights() -> None:
    hs = HealthScore()
    assert hs.score() == 100.0
    # 100 - 10*2 - 5*1 - 0.2*10 - 0.1*5 = 72.5
    assert hs.score(loops=2, breaker_trips=1, p95_latency_s=10, cost_usd=5) == 72.5
    assert HealthScore(loop_weight=1).score(loops=2) == 98.0


def test_variant_config_reads_as_attributes() -> None:
    v = Variant("a", {"style": "terse", "loop_mode": "off"})
    assert v.style == "terse"
    assert v.loop_mode == "off"
    assert v.name == "a"  # real fields untouched
    with pytest.raises(AttributeError, match="style2"):
        _ = v.style2


def test_variant_knobs_as_keywords() -> None:
    _install()
    e = Experiment("e").variant("terse", style="terse", model="gemini-2.5-flash")
    v = e._variants[0]
    assert v.style == "terse" and v.model == "gemini-2.5-flash"
    # config= still accepted; keywords win on collision
    e.variant("mix", config={"style": "old", "top_p": 0.9}, style="new")
    assert e._variants[1].style == "new" and e._variants[1].top_p == 0.9


def test_health_score_penalizes_failures() -> None:
    hs = HealthScore()
    assert hs.score(failures=1) == 80.0
    # a variant that errored must not out-score a clean but slower/pricier one
    assert hs.score(failures=1) < hs.score(p95_latency_s=5, cost_usd=0.05)


def test_metadata_autofills_and_splits_span_vs_log() -> None:
    md = ExperimentMetadata.collect(description="A/B", author="me")
    assert md.python_version and md.kit_version
    log_attrs = md.log_attributes()
    assert log_attrs[semconv.EXPERIMENT_DESCRIPTION] == "A/B"
    assert log_attrs[semconv.EXPERIMENT_AUTHOR] == "me"
    # span tags stay lean: the description never rides every span
    assert semconv.EXPERIMENT_DESCRIPTION not in md.span_tags()
