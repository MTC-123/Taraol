from amr import semconv
from amr.provenance import origin_of_bad_output


def _tree() -> list[dict[str, object]]:
    # planner -> writer(flagged) -> critic -> router
    return [
        {"span_id": "1", "parent_span_id": "", "serviceName": "planner"},
        {
            "span_id": "2",
            "parent_span_id": "1",
            "serviceName": "writer",
            "attributes": {
                semconv.AGENTMESH_OUTPUT_FLAGGED: True,
                semconv.AGENTMESH_OUTPUT_CATEGORY: "hallucination",
            },
        },
        {"span_id": "3", "parent_span_id": "2", "serviceName": "critic"},
        {"span_id": "4", "parent_span_id": "3", "serviceName": "router"},
    ]


def test_backtracks_to_origin_and_lists_consumers() -> None:
    result = origin_of_bad_output(_tree())
    assert result == {
        "origin": "writer",
        "category": "hallucination",
        "consumers": ["critic", "router"],
    }


def test_clean_trace_returns_none() -> None:
    rows = [
        {"span_id": "1", "parent_span_id": "", "serviceName": "planner"},
        {"span_id": "2", "parent_span_id": "1", "serviceName": "writer"},
    ]
    assert origin_of_bad_output(rows) is None


def test_shallowest_flag_wins_when_multiple_flagged() -> None:
    rows = _tree()
    # critic also re-flags, but writer is closer to the root -> origin stays writer.
    rows[2]["attributes"] = {semconv.AGENTMESH_OUTPUT_FLAGGED: True}
    result = origin_of_bad_output(rows)
    assert result is not None
    assert result["origin"] == "writer"


def test_result_carries_no_content_only_service_and_category() -> None:
    result = origin_of_bad_output(_tree())
    assert set(result) == {"origin", "category", "consumers"}
