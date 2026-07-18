"""Small operator CLI with the same facts as the MCP explain tool."""

import argparse
import json
import os

from .explain import explain_trace


def main() -> None:
    parser = argparse.ArgumentParser(prog="amr")
    commands = parser.add_subparsers(dest="command", required=True)
    explain = commands.add_parser("explain", help="explain a trace using SigNoz data")
    explain.add_argument("trace_id")
    args = parser.parse_args()
    if args.command == "explain":
        # Import lazily so the pure explanation helpers remain dependency-light.
        from detection.signoz_client import ClickHouseClient, SigNozClient

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
            facts = explain_trace(
                args.trace_id,
                client.get_trace(args.trace_id),
                client.get_audit_events(args.trace_id),
            )
            print(json.dumps(facts, indent=2))
        finally:
            client.close()
