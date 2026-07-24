"""Per-step "replay" reconstruction — the LangSmith-style chain from trace rows.

``build_steps`` turns a trace's raw SigNoz span rows into an ordered list of agent
steps, each with its LLM input/output messages, tool calls (query + result), tokens
and direct cost. Prompt/output/tool text is only present when the producing agents ran
with content capture enabled; otherwise the chain shows structure + tokens + cost only.

Framework-neutral: it reads standard `gen_ai.*` attributes plus the project cost keys,
so it reconstructs any kit-instrumented agent's trace.
"""

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from . import semconv
from .attributes import AttrNames, attrs


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: Any = None
    result: Any = None


@dataclass(slots=True)
class Step:
    agent: str
    span_id: str
    conversation_id: str | None = None
    input_messages: Any = None
    output_messages: Any = None
    system_instructions: Any = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    direct_cost_usd: float | None = None
    tools: list[ToolCall] = field(default_factory=list)


def _attrs(span: Mapping[str, Any]) -> Mapping[str, Any]:
    value = span.get("attributes")
    return value if isinstance(value, Mapping) else {}


def _value(span: Mapping[str, Any], name: str) -> Any:
    return span.get(name, _attrs(span).get(name))


def _service(span: Mapping[str, Any]) -> str:
    resource = span.get("resource")
    if isinstance(resource, Mapping) and isinstance(resource.get("service.name"), str):
        return resource["service.name"]
    for name in ("service.name", "serviceName"):
        value = _value(span, name)
        if isinstance(value, str):
            return value
    return "unknown"


def _span_id(span: Mapping[str, Any]) -> str:
    return str(span.get("span_id", span.get("spanId", "")))


def _parent_id(span: Mapping[str, Any]) -> str:
    return str(span.get("parent_span_id", span.get("parentSpanId", "")) or "")


def _ts(span: Mapping[str, Any]) -> str:
    return str(span.get("timestamp", span.get("start_time", "")))


def _op(span: Mapping[str, Any]) -> str:
    value = _value(span, semconv.GEN_AI_OPERATION_NAME)
    return value if isinstance(value, str) else ""


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def _tool_name(span: Mapping[str, Any]) -> str:
    name = span.get("name", "")
    prefix = "execute_tool "
    return name[len(prefix) :] if isinstance(name, str) and name.startswith(prefix) else str(name)


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def build_steps(spans: Iterable[Mapping[str, Any]], names: AttrNames | None = None) -> list[Step]:
    """Reconstruct the ordered per-agent step chain from a trace's span rows."""

    names = names or attrs("agentmesh")
    rows = [dict(span) for span in spans]
    children: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for span in rows:
        children[_parent_id(span)].append(span)

    invoke_spans = sorted(
        (s for s in rows if _op(s) == semconv.INVOKE_AGENT), key=lambda s: (_ts(s), _span_id(s))
    )
    steps: list[Step] = []
    for inv in invoke_spans:
        step = Step(
            agent=_service(inv),
            span_id=_span_id(inv),
            conversation_id=(
                _value(inv, semconv.GEN_AI_CONVERSATION_ID)
                if isinstance(_value(inv, semconv.GEN_AI_CONVERSATION_ID), str)
                else None
            ),
        )
        for child in sorted(children.get(_span_id(inv), []), key=lambda s: (_ts(s), _span_id(s))):
            op = _op(child)
            if op == semconv.CHAT:
                step.input_messages = _maybe_json(_value(child, semconv.GEN_AI_INPUT_MESSAGES))
                step.output_messages = _maybe_json(_value(child, semconv.GEN_AI_OUTPUT_MESSAGES))
                step.system_instructions = _maybe_json(
                    _value(child, semconv.GEN_AI_SYSTEM_INSTRUCTIONS)
                )
                intok = _number(_value(child, semconv.GEN_AI_USAGE_INPUT_TOKENS))
                outok = _number(_value(child, semconv.GEN_AI_USAGE_OUTPUT_TOKENS))
                step.input_tokens = int(intok) if intok is not None else None
                step.output_tokens = int(outok) if outok is not None else None
                step.direct_cost_usd = _number(_value(child, names.cost_direct_usd))
            elif op == semconv.EXECUTE_TOOL:
                step.tools.append(
                    ToolCall(
                        name=_tool_name(child),
                        arguments=_maybe_json(_value(child, semconv.GEN_AI_TOOL_CALL_ARGUMENTS)),
                        result=_maybe_json(_value(child, semconv.GEN_AI_TOOL_CALL_RESULT)),
                    )
                )
        steps.append(step)
    return steps
