"""AgentLab runner: fire a baseline-vs-runaway experiment at the research-mesh planner.

One 5-agent stack, two variants under a single run_id: `baseline` converges (loop_mode
off); `runaway` storms the writer<->critic loop (loop_mode storm) so the kit's watcher
fires loop_detected + trips the per-edge breaker. No redeploy, no env flip — the loop mode
rides the payload per conversation.

    python -m research_mesh.experiment          # from demos/, with the stack up

Then compare — SigNoz is the dashboard (import the experiment-comparison dashboard), or
from the terminal::

    taraol experiment summary converge-vs-runaway

Needs OTEL_EXPORTER_OTLP_ENDPOINT pointing at the SigNoz collector (so the experiment_run
records land) and the planner reachable at PLANNER_START_URL.
"""

import os

import httpx

from taraol import Experiment, current_experiment, instrument

PLANNER_START_URL = os.environ.get("PLANNER_START_URL", "http://localhost:8000/start")
EXPERIMENT_ID = os.environ.get("AGENTLAB_EXPERIMENT_ID", "converge-vs-runaway")
USER_INPUT = os.environ.get("AGENTLAB_INPUT", "Summarize recent advances in solid-state batteries.")
FIRE_TIMEOUT_SEC = float(os.environ.get("AGENTLAB_FIRE_TIMEOUT_SEC", "180"))


def fire(ctx) -> None:
    """Kick one variant conversation at the planner, tagged with the shared run_id."""

    experiment = current_experiment()
    assert experiment is not None  # the builder sets this for the duration of the workload
    payload = {
        "conversation_id": f"{experiment.run_id[:8]}-{ctx.name}",
        "user_input": USER_INPUT,
        "experiment_id": experiment.id,
        "experiment_variant": ctx.name,
        "experiment_run_id": experiment.run_id,
        "loop_mode": ctx.loop_mode,
    }
    response = httpx.post(PLANNER_START_URL, json=payload, timeout=FIRE_TIMEOUT_SEC)
    response.raise_for_status()


def main() -> None:
    instrument("agentlab-runner")  # export the experiment_run records to SigNoz
    result = (
        Experiment(
            EXPERIMENT_ID,
            description="research-mesh: converging baseline vs runaway loop",
            author=os.environ.get("USER") or os.environ.get("USERNAME") or "",
        )
        .compare("baseline", loop_mode="off")
        .compare("runaway", loop_mode="storm")
        .run(fire)
    )
    print(f"run_id = {result.run_id}")
    for variant_result in result.results:
        print(
            f"  {variant_result.variant:<10} {variant_result.status}"
            f"  ({variant_result.duration_ms:.0f} ms)"
        )
    print(f"\nCompare:  taraol experiment summary {EXPERIMENT_ID}")


if __name__ == "__main__":
    main()
