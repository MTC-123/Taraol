"""Operator CLI: bundled SigNoz (up/down + dashboards) + incident explain / replay."""

import argparse
import os
import subprocess
import uuid

from . import assets


def _signoz(action: str) -> None:
    compose = assets.signoz_compose_path()
    if not compose.exists():
        raise SystemExit(f"bundled SigNoz compose not found at {compose}")
    env = dict(os.environ)
    if action == "up":
        if not env.get("SIGNOZ_TOKENIZER_JWT_SECRET"):
            env["SIGNOZ_TOKENIZER_JWT_SECRET"] = uuid.uuid4().hex
            print("note: generated a throwaway SIGNOZ_TOKENIZER_JWT_SECRET (set one to persist).")
        cmd = ["docker", "compose", "-f", str(compose), "up", "-d"]
    else:
        cmd = ["docker", "compose", "-f", str(compose), "down", "-v"]
    result = subprocess.run(cmd, env=env, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    if action == "up":
        print("\nSigNoz starting. UI: http://localhost:8080")
        print("Point your agents at it:  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317")
        print("Import dashboards:        otel-agent-kit dump-dashboards ./dashboards")
        print("Stop + wipe:              otel-agent-kit signoz down")


def main() -> None:
    parser = argparse.ArgumentParser(prog="otel-agent-kit")
    commands = parser.add_subparsers(dest="command", required=True)

    signoz = commands.add_parser("signoz", help="start/stop a local bundled SigNoz backend")
    signoz.add_argument("action", choices=["up", "down"])

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

    experiment = commands.add_parser(
        "experiment", help="AgentLab: compare experiment variants from SigNoz telemetry"
    )
    exp_sub = experiment.add_subparsers(dest="exp_command", required=True)
    exp_summary = exp_sub.add_parser("summary", help="per-variant cost/latency/loops/breakers/fails")
    exp_summary.add_argument("experiment_id")
    exp_summary.add_argument("--run", dest="run_id", default=None, help="limit to one run_id")
    exp_summary.add_argument(
        "--since", type=int, default=60, help="lookback window in minutes (default 60)"
    )
    exp_diff = exp_sub.add_parser("diff", help="compare two runs (cost/latency/loops deltas)")
    exp_diff.add_argument("run1")
    exp_diff.add_argument("run2")
    exp_diff.add_argument(
        "--since", type=int, default=60, help="lookback window in minutes (default 60)"
    )

    args = parser.parse_args()
    if args.command == "signoz":
        _signoz(args.action)
    elif args.command == "list-dashboards":
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
    elif args.command == "experiment":
        # Lazy import: the [detection] extra (httpx + SigNoz/ClickHouse client) is only
        # needed for the summary/diff read path.
        from . import experiment_report

        if args.exp_command == "summary":
            print(
                experiment_report.summarize(
                    args.experiment_id, run_id=args.run_id, since_sec=args.since * 60
                )
            )
        elif args.exp_command == "diff":
            print(experiment_report.diff(args.run1, args.run2, since_sec=args.since * 60))
