"""Operator CLI: aggregate incident facts, or a LangSmith-style per-step replay."""

import argparse
import json

from ..explain import explain_trace
from ..replay import Step, build_steps
from .client import SigNozMCPClient, format_explanation


def _as_text(value: object) -> str:
    if value is None:
        return "(not captured)"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _plain_messages(value: object, indent: str) -> str:
    """Decode a gen_ai message list to readable text (the wire stays standard JSON)."""

    if value is None:
        return "(not captured)"
    try:
        messages = json.loads(value) if isinstance(value, str) else value
        parts = [
            str(m["content"]) for m in messages if isinstance(m, dict) and m.get("content")
        ]
        if not parts:
            return _as_text(value)
        text = "\n\n".join(parts)
        return text.replace("\n", "\n" + indent)
    except (ValueError, TypeError):
        return _as_text(value)


def format_replay(trace_id: str, steps: list[Step]) -> str:
    """Render the per-step chain: each agent's input, output, tools, tokens, cost."""

    lines = [f"Trace replay — {trace_id}", "=" * 40]
    if not steps:
        lines.append("(no agent steps found)")
        return "\n".join(lines)
    for i, step in enumerate(steps, 1):
        cost = f"${step.direct_cost_usd:.4f}" if step.direct_cost_usd is not None else "n/a"
        toks = f"{step.input_tokens or 0}->{step.output_tokens or 0} tok"
        lines += [
            "",
            f"[{i}] {step.agent}   ({toks}, {cost})",
            f"    input:  {_plain_messages(step.input_messages, '            ')}",
            f"    output: {_plain_messages(step.output_messages, '            ')}",
        ]
        for tool in step.tools:
            lines.append(
                f"    tool {tool.name}: {_as_text(tool.arguments)} -> {_as_text(tool.result)}"
            )
    lines.append("")
    lines.append(
        "Tip: content shows '(not captured)' unless agents ran with OAK_CAPTURE_CONTENT=on."
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="taraol")
    commands = parser.add_subparsers(dest="command", required=True)
    explain = commands.add_parser("explain", help="explain a trace using SigNoz data")
    explain.add_argument("trace_id")
    explain.add_argument(
        "--replay",
        action="store_true",
        help="print the per-agent step chain (input/output/tools) instead of the summary",
    )
    args = parser.parse_args()
    if args.command == "explain":
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
