import httpx
import pytest

from amr import llm


def _canned_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "gemini-2.0-flash",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        },
        request=httpx.Request("POST", "http://x"),
    )


def test_fake_is_default_and_deterministic() -> None:
    a = llm.complete("hello", "gpt-4.1-mini")
    b = llm.complete("hello", "gpt-4.1-mini")
    assert a == b
    assert a.input_tokens >= 1000  # padded so USD rollups are legible


def test_gemini_routes_to_openai_compatible_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs) -> httpx.Response:
        captured["url"] = url
        captured["auth"] = kwargs["headers"].get("authorization")
        captured["model"] = kwargs["json"]["model"]
        return _canned_response()

    monkeypatch.setenv("AMR_LLM", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm.httpx, "post", fake_post)

    result = llm.complete("summarize", "gemini-2.0-flash")
    assert captured["url"] == llm._GEMINI_ENDPOINT
    assert captured["auth"] == "Bearer test-key"
    assert captured["model"] == "gemini-2.0-flash"
    assert result.input_tokens == 12 and result.output_tokens == 3
    assert result.finish_reason == "stop"


def test_gemini_without_key_raises(monkeypatch) -> None:
    monkeypatch.setenv("AMR_LLM", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AMR_LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm.complete("x", "gemini-2.0-flash")
