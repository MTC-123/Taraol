"""Hands-free 90-second live incident beat, driven only through supported surfaces."""

import os
import shutil
import subprocess
import time
from typing import Any
from uuid import uuid4

import httpx

from amr.explain import explain_trace
from amr.mcp_client import SigNozMCPClient, format_explanation


def fail(message: str) -> None:
    raise SystemExit(f"DEMO FAILED: {message}")


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


def main() -> None:
    timeout = int(os.environ.get("AMR_DEMO_TIMEOUT_SEC", "90"))
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
        ["docker", "compose", "--profile", "mcp", "up", "-d", "--wait"], check=True, env=env
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
    conversation = f"demo-loop-{uuid4().hex[:8]}"
    start = time.monotonic()
    response = httpx.post(
        "http://localhost:8000/start", json={"conversation_id": conversation}, timeout=30
    )
    response.raise_for_status()
    result = response.json()
    trace_id = result.get("_meta", {}).get("trace_id")
    if not isinstance(trace_id, str) or len(trace_id) != 32:
        fail(f"planner response did not include a trace id: {result}")
    deadline = start + timeout
    rows = wait_for(lambda: client.get_trace(trace_id), "five-agent trace", deadline)
    facts = explain_trace(trace_id, rows, ())
    if set(facts["services"]) != {"planner", "researcher", "writer", "critic", "router"}:
        fail(f"unexpected service mesh: {facts['services']}")
    if "writer" not in facts["cyclic_agents"] or "critic" not in facts["cyclic_agents"]:
        fail("storm trace did not include the writer/critic cycle")
    before = facts["direct_chat_cost_usd"]
    audit = wait_for(
        lambda: client.get_audit_events(trace_id), "firing alert and pause audit", deadline
    )
    firing = client.list_firing_alerts()
    if not firing:
        fail("no SigNoz alert instance is firing")
    time.sleep(5)
    after = explain_trace(trace_id, client.get_trace(trace_id), audit)["direct_chat_cost_usd"]
    if after != before:
        fail(f"cost continued after pause ({before:.4f} -> {after:.4f})")
    elapsed = time.monotonic() - start
    if elapsed > timeout:
        fail(f"incident beat exceeded {timeout}s ({elapsed:.1f}s)")
    print(f"Demo beat completed in {elapsed:.1f}s; conversation={conversation}")
    print(format_explanation(explain_trace(trace_id, client.get_trace(trace_id), audit)))


if __name__ == "__main__":
    main()
