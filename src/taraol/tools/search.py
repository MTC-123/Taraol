"""Web search tool with a real (Tavily) provider and a deterministic offline fake.

Provider is selected by ``OAK_SEARCH``: ``fake`` (default; deterministic, offline, for
tests/CI) or ``tavily`` (real web search, needs ``TAVILY_API_KEY``). The result is a list
of :class:`SearchHit`; a caller records the query + results on a tool span via
``Instrument.tool(name, arguments=query)`` + ``ToolSpan.set_result(...)``.
"""

import json
import os
from dataclasses import dataclass

_TAVILY_ENDPOINT = "https://api.tavily.com/search"


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str


def _fake_search(query: str, max_results: int) -> list[SearchHit]:
    """Deterministic, offline results derived from the query (no network)."""

    slug = "-".join(query.lower().split())[:60] or "query"
    return [
        SearchHit(
            title=f"Result {i + 1} for: {query}",
            url=f"https://example.com/{slug}/{i + 1}",
            snippet=f"Deterministic offline snippet {i + 1} about {query}.",
        )
        for i in range(max(1, min(max_results, 5)))
    ]


def _tavily_search(query: str, max_results: int) -> list[SearchHit]:
    import httpx

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required when OAK_SEARCH=tavily")
    response = httpx.post(
        _TAVILY_ENDPOINT,
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    return [
        SearchHit(
            title=str(r.get("title", "")),
            url=str(r.get("url", "")),
            snippet=str(r.get("content", "")),
        )
        for r in results[:max_results]
    ]


def web_search(query: str, *, max_results: int = 5) -> list[SearchHit]:
    """Search the web. ``OAK_SEARCH`` selects the provider; ``fake`` is the default."""

    provider = os.environ.get("OAK_SEARCH", "fake").lower()
    if provider == "tavily":
        return _tavily_search(query, max_results)
    return _fake_search(query, max_results)


def hits_to_json(hits: list[SearchHit]) -> str:
    """Compact JSON for capturing search results on a tool span."""

    return json.dumps(
        [{"title": h.title, "url": h.url, "snippet": h.snippet} for h in hits],
        ensure_ascii=False,
    )
