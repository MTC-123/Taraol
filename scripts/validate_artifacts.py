"""Fast, offline checks for committed demo artifacts."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def main() -> None:
    for path in (ROOT / "signoz" / "dashboards").glob("*.json"):
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        widgets = dashboard["widgets"]
        assert 1 <= len(widgets) <= 12, f"{path}: panel count"
        assert dashboard["layout"][0]["x"] == 0 and dashboard["layout"][0]["y"] == 0
        assert widgets[0]["panelTypes"] == "value", f"{path}: primary KPI must be a value"
        for widget in widgets:
            assert widget.get("thresholds"), f"{path}: {widget['title']} has no thresholds"
    terraform = (ROOT / "signoz" / "terraform" / "alerts.tf").read_text(encoding="utf-8")
    assert "signoz_alert" in terraform and "signoz_route_policy" in terraform
    assert "http" not in terraform.replace("http://controller:8000/alert", "")
    assert "STORM_SAFETY_CAP = 24" in (ROOT / "src" / "amr" / "mesh.py").read_text()
    print("artifact validation passed")


if __name__ == "__main__":
    main()
