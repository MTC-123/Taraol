"""Minimal stdio MCP server for grounded loop explanations."""

import os
from typing import Any

from amr.explain import explain_trace
from detection.signoz_client import ClickHouseClient, SigNozClient


def explain_this_loop(trace_id: str) -> dict[str, Any]:
    """Fetch a real trace from SigNoz and return traceable loop facts."""

    clickhouse_url = os.environ.get("SIGNOZ_CLICKHOUSE_URL")
    client = (
        ClickHouseClient(clickhouse_url)
        if clickhouse_url
        else SigNozClient(
            os.environ.get("SIGNOZ_URL", "http://localhost:8080"),
            os.environ.get("SIGNOZ_API_KEY", ""),
        )
    )
    try:
        return explain_trace(
            trace_id, client.get_trace(trace_id), client.get_audit_events(trace_id)
        )
    finally:
        client.close()


def main() -> None:
    """Start the MCP server when the optional MCP SDK is installed."""

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - startup guidance
        raise SystemExit("Install the optional 'mcp' dependency to run the MCP server.") from exc
    server = FastMCP("agent-mesh-radar")
    server.tool()(explain_this_loop)
    server.run()


if __name__ == "__main__":
    main()
