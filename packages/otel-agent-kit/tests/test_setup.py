import otel_agent_kit.setup as setup
from otel_agent_kit import Settings, instrument


def test_instrument_installs_provider_only_once(monkeypatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(setup, "_PROVIDER_INSTALLED", False)
    monkeypatch.setattr(setup, "_install_provider", lambda settings: calls.__setitem__("n", calls["n"] + 1))

    first = instrument("planner")
    second = instrument("writer")

    assert calls["n"] == 1  # idempotent: one provider for the process
    assert first.settings.service_name == "planner"
    assert second.settings.service_name == "writer"


def test_settings_overrides_beat_env(monkeypatch) -> None:
    monkeypatch.setenv("OAK_ATTR_NAMESPACE", "fromenv")
    settings = Settings.from_env("planner", attr_namespace="override")
    assert settings.attr_namespace == "override"


def test_cost_model_override_via_dict(monkeypatch) -> None:
    monkeypatch.setattr(setup, "_PROVIDER_INSTALLED", True)  # skip real provider install
    kit = instrument("planner", cost_model={"m": {"input_per_1k": 1.0, "output_per_1k": 2.0}})
    assert kit.cost_model.cost_of("m", 1000, 1000) == (3.0, False)
