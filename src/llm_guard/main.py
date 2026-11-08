"""FastAPI アプリ。uvicorn llm_guard.main:app で起動する。"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from llm_guard import __version__
from llm_guard.config import Settings, load_policy, load_rules
from llm_guard.detectors.rules import RulesDetector
from llm_guard.pipeline import Guard, InspectionResult


class InspectRequest(BaseModel):
    text: str = Field(min_length=0, max_length=100_000)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    policy = load_policy(settings.policy_path)
    rules = load_rules(settings.rules_path)

    detectors = []
    if policy.stages.rules:
        detectors.append(RulesDetector(rules))
    guard = Guard(policy=policy, detectors=detectors)

    app = FastAPI(title="llm-guard-gateway", version=__version__)
    app.state.guard = guard
    app.state.settings = settings

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "mode": policy.mode,
            "stages": {d.name: {"enabled": True, "ready": d.ready()} for d in detectors},
        }

    @app.post("/v1/inspect", response_model=InspectionResult)
    def inspect(req: InspectRequest) -> InspectionResult:
        return guard.inspect(req.text)

    return app


app = create_app()
