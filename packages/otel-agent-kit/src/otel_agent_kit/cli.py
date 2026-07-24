"""Small operator CLI: export the bundled SigNoz dashboards."""

import argparse

from . import assets


def main() -> None:
    parser = argparse.ArgumentParser(prog="otel-agent-kit")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list-dashboards", help="list bundled dashboards")
    dump = commands.add_parser("dump-dashboards", help="write bundled dashboards to a directory")
    dump.add_argument("dest", help="output directory")

    args = parser.parse_args()
    if args.command == "list-dashboards":
        for name in assets.list_dashboards():
            print(name)
    elif args.command == "dump-dashboards":
        for path in assets.dump_dashboards(args.dest):
            print(path)
