import json

import httpx

from llm_guard.detectors.llm_judge import OllamaJudge, _parse


def fake_ollama(responses: list):
    """responses の要素: dict（JSON で返す content）、str（生の content）、
    int（HTTP ステータス）、"timeout"。"""
    calls = {"n": 0, "bodies": []}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["bodies"].append(json.loads(request.content))
        item = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        if item == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        if isinstance(item, int):
            return httpx.Response(item, json={"error": "x"})
        content = json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaJudge("http://ollama", "test-model", client=client), calls


def test_parse_accepts_json_with_surrounding_text():
    v = _parse(
        '判定: {"sensitive": true, "kinds": ["person_name", "bogus"], "reason": "氏名"} 以上'
    )
    assert v and v.sensitive and v.kinds == ["person_name"] and v.reason == "氏名"


def test_parse_rejects_broken_or_untyped_json():
    assert _parse("わかりません") is None
    assert _parse('{"sensitive": "yes"}') is None


def test_sensitive_verdict_and_request_shape():
    judge, calls = fake_ollama([{"sensitive": True, "kinds": ["person_name"], "reason": "氏名"}])
    v = judge("山田太郎に送る")
    assert v.sensitive and v.kinds == ["person_name"] and v.error is None
    body = calls["bodies"][0]
    assert body["model"] == "test-model" and body["format"] == "json" and body["stream"] is False
    assert body["messages"][-1] == {"role": "user", "content": "山田太郎に送る"}
    assert body["messages"][0]["role"] == "system"


def test_retries_once_on_invalid_json_then_succeeds():
    judge, calls = fake_ollama(["ええと…", {"sensitive": False, "kinds": [], "reason": "地名"}])
    v = judge("長野支店に行く")
    assert v.sensitive is False and v.error is None
    assert calls["n"] == 2


def test_gives_up_after_retry_with_invalid_json():
    judge, calls = fake_ollama(["???"])
    v = judge("x")
    assert v.error == "invalid_json" and calls["n"] == 2


def test_timeout_is_reported_without_retry():
    judge, calls = fake_ollama(["timeout"])
    v = judge("x")
    assert v.error == "timeout" and calls["n"] == 1


def test_http_error_is_reported():
    judge, _ = fake_ollama([500])
    assert judge("x").error == "http 500"
