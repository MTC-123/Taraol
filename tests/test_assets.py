from otel_agent_kit import assets


def test_lists_bundled_dashboards() -> None:
    names = assets.list_dashboards()
    assert {"conversation-budget", "cost-per-agent", "cost-per-edge"} <= set(names)


def test_dashboard_parses_as_json() -> None:
    data = assets.dashboard("cost-per-edge")
    assert isinstance(data, dict)


def test_dump_dashboards_writes_files(tmp_path) -> None:
    written = assets.dump_dashboards(tmp_path)
    assert len(written) == len(assets.list_dashboards())
    assert all(path.exists() for path in written)


def test_bundled_signoz_compose_is_present() -> None:
    compose = assets.signoz_compose_path()
    assert compose.exists()
    assert compose.name == "compose.yaml"
    assert (assets.signoz_deploy_path() / "casting.yaml").exists()


def test_terraform_module_is_present() -> None:
    assert (assets.terraform_module_path() / "alerts.tf").exists()
