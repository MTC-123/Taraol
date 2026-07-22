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
