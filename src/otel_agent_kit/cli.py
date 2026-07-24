"""Operator CLI: bundled SigNoz dashboards + incident explain / per-step replay."""

import argparse

from . import assets


def main() -> None:
    parser = argparse.ArgumentParser(prog="otel-agent-kit")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list-dashboards", help="list bundled dashboards")
    dump = commands.add_parser("dump-dashboards", help="write bundled dashboards to a directory")
    dump.add_argument("dest", help="output directory")

    explain = commands.add_parser("explain", help="explain a trace via the SigNoz MCP server")
    explain.add_argument("trace_id")
    explain.add_argument(
        "--replay",
        action="store_true",
        help="per-agent step chain (input/output/tools) instead of the summary",
    )

    args = parser.parse_args()
    if args.command == "list-dashboards":
        for name in assets.list_dashboards():
            print(name)
    elif args.command == "dump-dashboards":
        for path in assets.dump_dashboards(args.dest):
            print(path)
    elif args.command == "explain":
        # Lazy import: the [mcp] extra is only needed for this command.
        from .explain import explain_trace
        from .mcp.cli import format_replay
        from .mcp.client import SigNozMCPClient, format_explanation
        from .replay import build_steps

        client = SigNozMCPClient()
        try:
            spans = client.get_trace(args.trace_id)
            if args.replay:
                print(format_replay(args.trace_id, build_steps(spans)))
            else:
                facts = explain_trace(args.trace_id, spans, client.get_audit_events(args.trace_id))
                print(format_explanation(facts))
        finally:
            client.close()
