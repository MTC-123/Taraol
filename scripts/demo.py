"""Hands-free 90-second live incident beat.

Local mode (default) needs only Docker and uv: real agents, real loop-watcher
detection over ClickHouse, real controller pause, real audit trail. The one
substitution is the alert-delivery hop: this script sends the controller the
same Alertmanager-shaped webhook that the Terraform-provisioned SigNoz rule
sends in full mode (`make demo-full`).
"""

import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

import httpx

from amr.explain import explain_trace
from amr.mcp_client import SigNozMCPClient, format_explanation
from detection.signoz_client import ClickHouseClient, TimeRange, conversation_cost_query

# The post-mortem uses characters (e.g. "→") that Windows' legacy cp1252
# console encoding cannot print.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLICKHOUSE_URL = "http://localhost:8123"
PLANNER_URL = "http://localhost:8000"
CONTROLLER_URL = "http://localhost:8002"


def fail(message: str) -> None:
    raise SystemExit(f"DEMO FAILED: {message}")


def cue(message: str) -> None:
    print(f"\n>>> {message}", flush=True)


def wait_for(predicate: Any, description: str, deadline: float) -> Any:
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:  # services legitimately start at different speeds
            last = exc
        time.sleep(2)
    suffix = f" ({last})" if last else ""
    fail(f"timed out waiting for {description}{suffix}")


def start_conversation() -> tuple[str, str]:
    conversation = f"demo-loop-{uuid4().hex[:8]}"
    response = httpx.post(
        f"{PLANNER_URL}/start", json={"conversation_id": conversation}, timeout=30
    )
    response.raise_for_status()
    result = response.json()
    trace_id = result.get("_meta", {}).get("trace_id")
    if not isinstance(trace_id, str) or len(trace_id) != 32:
        fail(f"planner response did not include a trace id: {result}")
    return conversation, trace_id


def mesh_facts(trace_id: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    # Spans ingest asynchronously; treat a partial trace as "not yet", not failure.
    if not rows:
        return None
    facts = explain_trace(trace_id, rows, ())
    if set(facts["services"]) != {"planner", "researcher", "writer", "critic", "router"}:
        return None
    if not {"writer", "critic"} <= set(facts["cyclic_agents"]):
        return None
    return facts


def finish(start: float, timeout: int, conversation: str, facts: dict[str, Any]) -> None:
    elapsed = time.monotonic() - start
    if elapsed > timeout:
        fail(f"incident beat exceeded {timeout}s ({elapsed:.1f}s)")
    cue("WATCH: Dashboards -> Agent Mesh - Conversation Budget; the cost line flatlines")
    print(f"\nDemo beat completed in {elapsed:.1f}s; conversation={conversation}")
    print("\nPost-mortem (what explain_this_loop tells an MCP host):")
    print(format_explanation(facts))
    print(f"\nReplay any time: uv run amr explain {facts['trace_id']}")


def merge_number_attributes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # ClickHouse stores numeric span attributes (cost) in a separate map.
    for row in rows:
        numbers = row.pop("attributes_number", None)
        attributes = row.get("attributes")
        if isinstance(attributes, dict) and isinstance(numbers, dict):
            attributes.update(numbers)
    return rows


def clickhouse_signal(conversation: str) -> dict[str, Any] | None:
    escaped = conversation.replace("'", "\\'")
    sql = f"""
        SELECT attributes_string AS attributes
        FROM signoz_logs.distributed_logs_v2
        WHERE body = 'loop_detected' AND attributes_string['conversation_id'] = '{escaped}'
        ORDER BY timestamp DESC LIMIT 1
    """
    response = httpx.post(
        f"{CLICKHOUSE_URL}/?default_format=JSONEachRow", content=sql.encode(), timeout=10
    )
    response.raise_for_status()
    for line in response.text.splitlines():
        return json.loads(line)
    return None


def conversation_cost(client: ClickHouseClient, conversation: str) -> float:
    end_ms = int(time.time() * 1000)
    rows = client.run_builder_query(
        conversation_cost_query(conversation), TimeRange(end_ms - 3_600_000, end_ms)
    )
    for row in rows:
        value = row.get("cost_usd")
        if isinstance(value, (int, float)):
            return round(float(value), 4)
    return 0.0


def run_local(timeout: int) -> None:
    env = os.environ | {"AMR_LOOP_MODE": "storm"}
    if not env.get("SIGNOZ_TOKENIZER_JWT_SECRET"):
        # Hands-free from a clean checkout: a throwaway signing key keeps SigNoz
        # bootable; put a stable one in .env to keep browser sessions valid.
        env["SIGNOZ_TOKENIZER_JWT_SECRET"] = uuid4().hex
        print("note: generated a throwaway SIGNOZ_TOKENIZER_JWT_SECRET; set one in .env to persist")
    up = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.demo.yml",
            "up",
            "-d",
            "--build",
            "--wait",
        ],
        check=False,
        env=env,
    )
    if up.returncode != 0:
        # `--wait` reports SigNoz's one-shot init containers (migrator, user
        # scripts) as failures once they exit; the readiness probes below are
        # the real gate.
        print("note: compose --wait returned nonzero; verifying readiness directly")
    client = ClickHouseClient(CLICKHOUSE_URL)
    wait_for(
        lambda: httpx.get(f"{CLICKHOUSE_URL}/ping", timeout=5).text.strip() == "Ok.",
        "ClickHouse readiness",
        time.monotonic() + 60,
    )
    wait_for(
        lambda: httpx.get(PLANNER_URL, timeout=5).status_code < 500,
        "planner readiness",
        time.monotonic() + 60,
    )
    cue("WATCH: open http://localhost:8080 -> APM -> Service Map (last 5 minutes)")
    conversation, trace_id = start_conversation()
    start = time.monotonic()
    deadline = start + timeout
    wait_for(
        lambda: mesh_facts(trace_id, merge_number_attributes(client.get_trace(trace_id))),
        "five-agent trace with the writer/critic cycle",
        deadline,
    )
    cue("NOW: click the red critic -> writer edge; open the demo-loop-* trace waterfall")
    signal = wait_for(
        lambda: clickhouse_signal(conversation), "loop-watcher loop_detected signal", deadline
    )
    attributes = signal.get("attributes", {})
    edge = attributes.get("edge", "critic -> writer")
    print(
        "\n[local mode] delivering the alert webhook to the controller; "
        "SigNoz Alertmanager performs this hop in `make demo-full`"
    )
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "loop-detected",
                    "conversation_id": conversation,
                    "edge": edge,
                    "trace_id": trace_id,
                },
            }
        ]
    }
    response = httpx.post(f"{CONTROLLER_URL}/alert", json=payload, timeout=10)
    response.raise_for_status()
    if response.json().get("accepted", 0) < 1:
        fail(f"controller did not accept the alert: {response.json()}")
    cue("WATCH: Logs filtered by this trace_id; agent_paused audit appears")
    audit = wait_for(lambda: client.get_audit_events(trace_id), "pause audit event", deadline)

    def flatlined() -> bool:
        before = conversation_cost(client, conversation)
        time.sleep(5)
        return conversation_cost(client, conversation) == before

    wait_for(flatlined, "conversation cost flatline after pause", deadline)
    facts = explain_trace(trace_id, merge_number_attributes(client.get_trace(trace_id)), audit)
    finish(start, timeout, conversation, facts)


def run_full(timeout: int) -> None:
    if not shutil.which("terraform"):
        fail("Terraform is required for the approved alert provisioning path")
    api_key = os.environ.get("SIGNOZ_API_KEY")
    if not api_key:
        fail(
            "official MCP/terraform verification needs a supported SigNoz credential; "
            "see docs/DEMO.md"
        )
    env = os.environ | {
        "AMR_LOOP_MODE": "storm",
        "TF_VAR_signoz_url": os.environ.get("SIGNOZ_URL", "http://localhost:8080"),
        "TF_VAR_signoz_api_key": api_key,
    }
    subprocess.run(
        ["docker", "compose", "--profile", "mcp", "up", "-d", "--build", "--wait"],
        check=True,
        env=env,
    )
    subprocess.run(
        ["terraform", "-chdir=signoz/terraform", "init", "-backend=false"], check=True, env=env
    )
    subprocess.run(
        ["terraform", "-chdir=signoz/terraform", "apply", "-auto-approve"],
        check=True,
        env=env,
    )
    client = SigNozMCPClient()
    wait_for(
        lambda: client.list_firing_alerts() is not None,
        "SigNoz MCP readiness",
        time.monotonic() + 30,
    )
    cue("WATCH: open http://localhost:8080 -> APM -> Service Map (last 5 minutes)")
    conversation, trace_id = start_conversation()
    start = time.monotonic()
    deadline = start + timeout
    facts = wait_for(
        lambda: mesh_facts(trace_id, client.get_trace(trace_id)),
        "five-agent trace with the writer/critic cycle",
        deadline,
    )
    cue("NOW: click the red critic -> writer edge; open the demo-loop-* trace waterfall")
    before = facts["direct_chat_cost_usd"]
    audit = wait_for(
        lambda: client.get_audit_events(trace_id), "firing alert and pause audit", deadline
    )
    if not client.list_firing_alerts():
        fail("no SigNoz alert instance is firing")
    time.sleep(5)
    after = explain_trace(trace_id, client.get_trace(trace_id), audit)["direct_chat_cost_usd"]
    if after != before:
        fail(f"cost continued after pause ({before:.4f} -> {after:.4f})")
    finish(start, timeout, conversation, explain_trace(trace_id, client.get_trace(trace_id), audit))


def main() -> None:
    timeout = int(os.environ.get("AMR_DEMO_TIMEOUT_SEC", "90"))
    full = "--full" in sys.argv[1:] or os.environ.get("AMR_DEMO_MODE", "local") == "full"
    if full:
        run_full(timeout)
    else:
        run_local(timeout)


if __name__ == "__main__":
    main()
