"""評価・テスト・docker compose 用の OpenAI 互換モック。最後の user メッセージをそのまま返す。

起動: python -m llm_guard.mock_llm  （既定ポート 8001）
"""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel


class ChatRequest(BaseModel):
    model: str = "mock"
    messages: list[dict]


def create_mock_app() -> FastAPI:
    app = FastAPI(title="mock-llm")

    @app.get("/v1/models")
    def models() -> dict:
        return {"object": "list", "data": [{"id": "mock", "object": "model"}]}

    @app.post("/v1/chat/completions")
    def chat(req: ChatRequest) -> dict:
        last_user = next(
            (m for m in reversed(req.messages) if m.get("role") == "user"), {"content": ""}
        )
        content = last_user.get("content", "")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return {
            "id": f"chatcmpl-mock-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"echo: {content}"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return app


app = create_mock_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
