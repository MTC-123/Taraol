import os

from amr.mesh import BASE_EDGES, next_targets


def test_default_mesh_is_the_declared_cross_service_chain() -> None:
    previous = os.environ.get("AMR_LOOP_MODE")
    os.environ["AMR_LOOP_MODE"] = "off"
    try:
        assert tuple((source, next_targets(source)[0]) for source, _ in BASE_EDGES) == BASE_EDGES
    finally:
        if previous is None:
            os.environ.pop("AMR_LOOP_MODE", None)
        else:
            os.environ["AMR_LOOP_MODE"] = previous
