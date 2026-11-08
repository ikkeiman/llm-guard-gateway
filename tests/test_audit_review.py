import httpx
import pytest

from llm_guard.audit import AuditLog
from llm_guard.config import Settings, load_policy
from llm_guard.factory import build_guard
from llm_guard.forwarder import OpenAICompatForwarder
from llm_guard.main import create_app
from llm_guard.mock_llm import create_mock_app
from llm_guard.review import ReviewQueue


def test_audit_log_refuses_raw_text(tmp_path):
    log = AuditLog(tmp_path / "a.db")
    with pytest.raises(AssertionError):
        log.record(
            endpoint="/x",
            decision="mask",
            stages=["rules"],
            findings=[{"kind": "phone", "text": "090-1234-5678"}],
            timings_ms={},
            total_ms=1.0,
        )


def test_audit_log_roundtrip(tmp_path):
    log = AuditLog(tmp_path / "a.db")
    log.record(
        endpoint="/v1/inspect",
        decision="mask",
        stages=["rules", "ner"],
        findings=[{"kind": "phone", "start": 3, "end": 16, "confidence": 0.95, "stage": "rules"}],
        timings_ms={"rules": 0.1, "ner": 12.0},
        total_ms=12.3,
    )
    rows = log.recent()
    assert log.count() == 1
    assert rows[0]["decision"] == "mask" and rows[0]["stages"] == ["rules", "ner"]
    assert rows[0]["findings"][0]["kind"] == "phone"


def test_review_queue_drops_request_body_on_resolve(tmp_path):
    q = ReviewQueue(tmp_path / "r.db")
    rid = q.enqueue(
        {"messages": [{"role": "user", "content": "秘密"}]}, None, {"decision": "review"}
    )
    assert q.list_pending()[0]["id"] == rid
    assert q.get(rid)["request"]["messages"][0]["content"] == "秘密"
    q.resolve(rid, "reject")
    item = q.get(rid)
    assert item["status"] == "rejected" and item["request"] is None
    assert q.list_pending() == []


@pytest.fixture
async def review_client(tmp_path):
    mock_transport = httpx.ASGITransport(app=create_mock_app())
    async with httpx.AsyncClient(transport=mock_transport, base_url="http://mock") as mock_client:
        forwarder = OpenAICompatForwarder("http://mock/v1", client=mock_client)
        policy = load_policy("config/policy.yaml")
        policy = policy.model_copy(
            update={
                "mode": "review",
                "stages": policy.stages.model_copy(update={"ner": False, "llm_judge": "off"}),
                "uncertain_without_judge": "review",
            }
        )
        settings = Settings(data_dir=tmp_path)
        guard = build_guard(policy, settings)
        app = create_app(settings, forwarder=forwarder, guard=guard)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c, app


async def test_review_flow_approve_sends_masked(review_client):
    client, app = review_client
    body = {
        "model": "mock",
        "messages": [{"role": "user", "content": "連絡先 taro@example.com に送って"}],
    }
    r = await client.post("/v1/chat/completions", json=body)
    assert r.status_code == 202 and r.headers["x-guard-decision"] == "review"
    rid = r.json()["review_id"]

    pending = (await client.get("/v1/review")).json()["pending"]
    assert [p["id"] for p in pending] == [rid]
    assert "taro@example.com" not in str(pending)  # 一覧に原文は出ない

    r2 = await client.post(f"/v1/review/{rid}", json={"action": "approve", "send": "masked"})
    assert r2.status_code == 200
    assert r2.json()["choices"][0]["message"]["content"] == "echo: 連絡先 <EMAIL_1> に送って"
    assert r2.headers["x-guard-decision"] == "review-approved"

    # 二重承認は 409、解決後は原文が消えている
    r3 = await client.post(f"/v1/review/{rid}", json={"action": "approve"})
    assert r3.status_code == 409
    assert app.state.reviews.get(rid)["request"] is None
    assert app.state.audit.count() == 1
    assert app.state.audit.recent()[0]["review_id"] == rid


async def test_review_reject_and_unknown_id(review_client):
    client, _ = review_client
    body = {"model": "mock", "messages": [{"role": "user", "content": "TEL 090-1234-5678"}]}
    rid = (await client.post("/v1/chat/completions", json=body)).json()["review_id"]
    r = await client.post(f"/v1/review/{rid}", json={"action": "reject"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert (await client.post("/v1/review/nope", json={"action": "reject"})).status_code == 404
