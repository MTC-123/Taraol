"""Small operator CLI with the same facts as the MCP explain tool."""

import argparse

from .explain import explain_trace
from .mcp_client import SigNozMCPClient, format_explanation


def main() -> None:
    parser = argparse.ArgumentParser(prog="amr")
    commands = parser.add_subparsers(dest="command", required=True)
    explain = commands.add_parser("explain", help="explain a trace using SigNoz data")
    explain.add_argument("trace_id")
    args = parser.parse_args()
    if args.command == "explain":
        client = SigNozMCPClient()
        try:
            facts = explain_trace(
                args.trace_id,
                client.get_trace(args.trace_id),
                client.get_audit_events(args.trace_id),
            )
            print(format_explanation(facts))
        finally:
            client.close()
