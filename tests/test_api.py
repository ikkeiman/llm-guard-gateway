import httpx
import pytest

from llm_guard.forwarder import OpenAICompatForwarder
from llm_guard.main import create_app
from llm_guard.mock_llm import create_mock_app


@pytest.fixture
async def mock_client():
    transport = httpx.ASGITransport(app=create_mock_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        yield c


@pytest.fixture
async def client(mock_client):
    forwarder = OpenAICompatForwarder("http://mock/v1", client=mock_client)
    app = create_app(forwarder=forwarder)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def chat_body(*contents: str, system: str | None = None) -> dict:
    msgs = [{"role": "user", "content": c} for c in contents]
    if system:
        msgs.insert(0, {"role": "system", "content": system})
    return {"model": "mock", "messages": msgs}


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["stages"]["rules"]["ready"] is True
    assert body["stages"]["llm_judge"]["enabled"] is False  # judge 未接続


async def test_inspect_clean_text(client):
    r = await client.post("/v1/inspect", json={"text": "明日の定例は10時からです"})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "allow"
    assert body["findings"] == []
    assert r.headers["x-guard-decision"] == "allow"


async def test_inspect_detects_phone_and_masks(client):
    r = await client.post("/v1/inspect", json={"text": "折り返し 090-1234-5678 へ"})
    body = r.json()
    assert body["decision"] == "mask"
    assert body["masked_text"] == "折り返し <PHONE_1> へ"
    assert body["findings"][0]["kind"] == "phone"


async def test_chat_clean_is_forwarded(client):
    r = await client.post("/v1/chat/completions", json=chat_body("今日の議題をまとめて"))
    assert r.status_code == 200
    assert r.headers["x-guard-decision"] == "allow"
    assert r.json()["choices"][0]["message"]["content"] == "echo: 今日の議題をまとめて"


async def test_chat_mask_sends_placeholders_upstream(client):
    r = await client.post(
        "/v1/chat/completions",
        json=chat_body("山田様へ 090-1234-5678 に連絡、メールは taro@example.com"),
    )
    assert r.status_code == 200
    assert r.headers["x-guard-decision"] == "mask"
    content = r.json()["choices"][0]["message"]["content"]
    assert "090-1234-5678" not in content and "taro@example.com" not in content
    assert "<PHONE_1>" in content and "<EMAIL_1>" in content


async def test_chat_block_on_my_number(client):
    r = await client.post(
        "/v1/chat/completions", json=chat_body("マイナンバー 1234-5678-9018 を登録して")
    )
    assert r.status_code == 403
    assert r.headers["x-guard-decision"] == "block"
    body = r.json()
    assert body["error"]["type"] == "guard_blocked"
    # 監査用の要約に原文は含まれない
    assert "1234" not in str(body["guard"]["findings"])


async def test_chat_same_name_shares_placeholder_across_messages(client):
    r = await client.post(
        "/v1/chat/completions",
        json=chat_body("氏名: 山田 太郎 の申請です", "氏名: 山田 太郎 を承認してください"),
    )
    assert r.status_code == 200
    # mock は最後の user メッセージを返す
    assert (
        r.json()["choices"][0]["message"]["content"]
        == "echo: 氏名: <PERSON_NAME_1> を承認してください"
    )


async def test_chat_rejects_stream(client):
    r = await client.post("/v1/chat/completions", json={**chat_body("hi"), "stream": True})
    assert r.status_code == 400


async def test_chat_requires_messages(client):
    r = await client.post("/v1/chat/completions", json={"model": "mock"})
    assert r.status_code == 400
