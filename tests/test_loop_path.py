import os

from amr.mesh import path_from


def test_loop_mode_alternates_writer_and_critic() -> None:
    previous = os.environ.get("AMR_LOOP_MODE")
    os.environ["AMR_LOOP_MODE"] = "on"
    try:
        path = path_from()
    finally:
        if previous is None:
            os.environ.pop("AMR_LOOP_MODE", None)
        else:
            os.environ["AMR_LOOP_MODE"] = previous
    assert path[:4] == ["planner", "researcher", "writer", "critic"]
    assert path[2:8] == ["writer", "critic", "writer", "critic", "writer", "critic"]
