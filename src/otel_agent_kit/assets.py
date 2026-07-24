"""Access bundled, importable SigNoz assets (dashboards) shipped in the wheel.

Adopters get ready-to-import dashboards for free — no need to copy JSON out of the
demo repo.  Use ``dashboard(name)`` for the parsed object or ``dump_dashboards(dir)``
to write them all out for a one-click SigNoz import.
"""

import json
from importlib import resources
from pathlib import Path
from typing import Any

_DASHBOARDS = "otel_agent_kit.data.dashboards"


def list_dashboards() -> list[str]:
    """Return the names (without extension) of the bundled dashboards."""

    root = resources.files(_DASHBOARDS)
    return sorted(entry.name[:-5] for entry in root.iterdir() if entry.name.endswith(".json"))


def dashboard(name: str) -> dict[str, Any]:
    """Return a bundled dashboard as a parsed JSON object."""

    text = resources.files(_DASHBOARDS).joinpath(f"{name}.json").read_text("utf-8")
    return json.loads(text)


def dump_dashboards(dest: str | Path) -> list[Path]:
    """Write every bundled dashboard JSON into ``dest``; returns the written paths."""

    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in list_dashboards():
        path = out / f"{name}.json"
        path.write_text(json.dumps(dashboard(name), indent=2), encoding="utf-8")
        written.append(path)
    return written


def list_alerts() -> list[str]:
    """Names of the bundled SigNoz alert-rule fixtures (loop/budget/edge/xconv)."""

    root = resources.files("otel_agent_kit.data.alerts")
    return sorted(e.name[:-5] for e in root.iterdir() if e.name.endswith(".json"))


def alert(name: str) -> dict[str, Any]:
    """Return a bundled alert-rule fixture as parsed JSON."""

    text = resources.files("otel_agent_kit.data.alerts").joinpath(f"{name}.json").read_text("utf-8")
    return json.loads(text)


def terraform_module_path() -> Path:
    """Filesystem path to the bundled Terraform alert module (point a `module {}` at it)."""

    return Path(str(resources.files("otel_agent_kit.data").joinpath("terraform")))
