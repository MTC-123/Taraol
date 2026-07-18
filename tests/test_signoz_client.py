import httpx

from detection.signoz_client import SigNozClient, TimeRange, velocity_query


def test_client_posts_v5_payload_with_api_key_and_normalizes_rows() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers["SIGNOZ-API-KEY"]
        captured["body"] = request.json() if hasattr(request, "json") else None
        return httpx.Response(200, json={"data": {"rows": [{"hop_count": 4}]}})

    # httpx Request has no public .json() helper; inspect the JSON body in a transport wrapper.
    def transport_handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["url"] = str(request.url)
        captured["key"] = request.headers["SIGNOZ-API-KEY"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"rows": [{"hop_count": 4}]}})

    client = SigNozClient(
        "http://signoz:8080",
        "secret",
        client=httpx.Client(transport=httpx.MockTransport(transport_handler)),
    )
    rows = client.run_builder_query(velocity_query(), TimeRange(100, 200))
    assert rows == [{"hop_count": 4}]
    assert captured["url"] == "http://signoz:8080/api/v5/query_range"
    assert captured["key"] == "secret"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["start"] == 100
    assert body["requestType"] == "table"
    assert body["compositeQuery"]["queries"][0]["spec"]["name"] == "velocity"
