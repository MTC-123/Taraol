import httpx

from taraol.tools import search


def test_fake_search_is_deterministic_and_offline(monkeypatch) -> None:
    monkeypatch.delenv("OAK_SEARCH", raising=False)
    a = search.web_search("climate policy 2026", max_results=3)
    b = search.web_search("climate policy 2026", max_results=3)
    assert a == b
    assert len(a) == 3
    assert all(isinstance(h, search.SearchHit) for h in a)
    assert "climate" in search.hits_to_json(a)


def test_tavily_routing_and_mapping(monkeypatch) -> None:
    def fake_post(url: str, **kwargs) -> httpx.Response:
        assert url == search._TAVILY_ENDPOINT
        assert kwargs["json"]["query"] == "otel"
        return httpx.Response(
            200,
            json={"results": [{"title": "T", "url": "https://x", "content": "snippet"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setenv("OAK_SEARCH", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setattr(httpx, "post", fake_post)
    hits = search.web_search("otel", max_results=1)
    assert hits == [search.SearchHit(title="T", url="https://x", snippet="snippet")]


def test_tavily_without_key_raises(monkeypatch) -> None:
    monkeypatch.setenv("OAK_SEARCH", "tavily")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    try:
        search.web_search("x")
    except RuntimeError as exc:
        assert "TAVILY_API_KEY" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
