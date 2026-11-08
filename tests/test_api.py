import httpx
import pytest

from llm_guard.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["stages"]["rules"]["ready"] is True


async def test_inspect_clean_text(client):
    r = await client.post("/v1/inspect", json={"text": "明日の定例は10時からです"})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "allow"
    assert body["findings"] == []
    assert "rules" in body["stages_run"]


async def test_inspect_detects_phone(client):
    r = await client.post("/v1/inspect", json={"text": "折り返し 090-1234-5678 へ"})
    body = r.json()
    assert body["decision"] != "allow"
    assert body["findings"][0]["kind"] == "phone"
    assert body["findings"][0]["stage"] == "rules"
