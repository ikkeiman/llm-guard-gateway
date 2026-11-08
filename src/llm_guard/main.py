"""FastAPI アプリ。uvicorn llm_guard.main:app で起動する。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from llm_guard import __version__
from llm_guard.config import ACTION_SEVERITY, Settings, load_policy
from llm_guard.factory import build_guard
from llm_guard.forwarder import OpenAICompatForwarder
from llm_guard.masking import MaskMap
from llm_guard.pipeline import Guard, InspectionResult

INSPECTED_ROLES = {"user", "system"}


class InspectRequest(BaseModel):
    text: str = Field(min_length=0, max_length=100_000)


def _message_text(content: Any) -> str:
    """OpenAI 形式の content（文字列、または text パーツの配列）から検査対象の文字列を取り出す。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def _replace_text(content: Any, new_text: str) -> Any:
    if isinstance(content, str):
        return new_text
    # 配列の場合は text パーツを1つにまとめて差し替える（画像などは残す）
    others = [p for p in content if not (isinstance(p, dict) and p.get("type") == "text")]
    return [{"type": "text", "text": new_text}, *others]


def create_app(
    settings: Settings | None = None,
    *,
    forwarder: OpenAICompatForwarder | None = None,
    guard: Guard | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    policy = load_policy(settings.policy_path)

    if guard is None:
        guard = build_guard(policy, settings)

    forwarder = forwarder or OpenAICompatForwarder(
        settings.openai_base_url, settings.openai_api_key, settings.openai_model
    )

    app = FastAPI(title="llm-guard-gateway", version=__version__)
    app.state.guard = guard
    app.state.settings = settings

    def guard_headers(decision: str, stages: list[str], n_findings: int) -> dict[str, str]:
        return {
            "x-guard-decision": decision,
            "x-guard-stages": ",".join(stages),
            "x-guard-findings": str(n_findings),
        }

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "mode": guard.policy.mode,
            "stages": {
                **{d.name: {"enabled": True, "ready": d.ready()} for d in guard.detectors},
                "llm_judge": {
                    "enabled": guard.judge_enabled(),
                    "policy": guard.policy.stages.llm_judge,
                },
            },
        }

    @app.post("/v1/inspect", response_model=InspectionResult)
    def inspect(req: InspectRequest, response: Response) -> InspectionResult:
        result = guard.inspect(req.text)
        response.headers.update(
            guard_headers(result.decision, result.stages_run, len(result.findings))
        )
        return result

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        body = await request.json()
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return JSONResponse(
                {"error": {"message": "messages が必要です", "type": "invalid_request_error"}},
                status_code=400,
            )
        if body.get("stream"):
            return JSONResponse(
                {
                    "error": {
                        "message": (
                            "stream=true は未対応です。応答を検査・復元するため全文を受け取ります"
                        ),
                        "type": "invalid_request_error",
                    }
                },
                status_code=400,
            )

        mask_map = MaskMap()
        results: list[InspectionResult] = []
        decision = "allow"
        new_messages = []
        for m in messages:
            if not isinstance(m, dict) or m.get("role") not in INSPECTED_ROLES:
                new_messages.append(m)
                continue
            text = _message_text(m.get("content"))
            r = guard.inspect(text, mask_map)
            results.append(r)
            if ACTION_SEVERITY[r.decision] > ACTION_SEVERITY[decision]:
                decision = r.decision
            if r.masked_text is not None:
                new_messages.append({**m, "content": _replace_text(m["content"], r.masked_text)})
            else:
                new_messages.append(m)

        stages = sorted({s for r in results for s in r.stages_run})
        n_findings = sum(len(r.findings) for r in results)
        headers = guard_headers(decision, stages, n_findings)
        summary = {
            "decision": decision,
            "findings": [f for r in results for f in r.public_findings()],
            "reasons": [r.reason for r in results if r.findings],
        }

        if decision == "block":
            return JSONResponse(
                {
                    "error": {
                        "message": "入力に個人情報または機微情報が含まれるため送信を拒否しました",
                        "type": "guard_blocked",
                        "code": "sensitive_input",
                    },
                    "guard": summary,
                },
                status_code=403,
                headers=headers,
            )
        if decision == "review":
            review_id = uuid.uuid4().hex
            return JSONResponse(
                {"status": "pending_review", "review_id": review_id, "guard": summary},
                status_code=202,
                headers=headers,
            )

        upstream = await forwarder.forward({**body, "messages": new_messages})
        data = upstream.body
        if (
            decision == "mask"
            and guard.policy.masking.restore_in_response
            and isinstance(data, dict)
            and len(mask_map)
        ):
            for ch in data.get("choices", []):
                msg = ch.get("message") if isinstance(ch, dict) else None
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    msg["content"] = mask_map.restore(msg["content"])
        return JSONResponse(data, status_code=upstream.status_code, headers=headers)

    return app


app = create_app()
