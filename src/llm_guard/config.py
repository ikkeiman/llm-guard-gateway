"""設定の読み込み。環境変数（接続先・パス）と YAML（判定ルール・ポリシー）を分けて扱う。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

Action = Literal["allow", "mask", "block", "review"]
ACTION_SEVERITY: dict[str, int] = {"allow": 0, "mask": 1, "review": 2, "block": 3}


# ---- rules.yaml -----------------------------------------------------------


class Rule(BaseModel):
    name: str
    kind: str
    pattern: str
    group: int = 0
    validator: str = "always"
    confidence: float = Field(ge=0.0, le=1.0)
    context_keywords: list[str] = Field(default_factory=list)
    context_window: int = 30
    confidence_with_context: float | None = Field(default=None, ge=0.0, le=1.0)
    description: str = ""


class RuleSet(BaseModel):
    rules: list[Rule]


def load_rules(path: str | Path) -> RuleSet:
    with open(path, encoding="utf-8") as f:
        return RuleSet.model_validate(yaml.safe_load(f))


# ---- policy.yaml ----------------------------------------------------------


class Thresholds(BaseModel):
    block_at: float = 0.90
    uncertain_low: float = 0.40
    uncertain_high: float = 0.90


class KindPolicy(BaseModel):
    min_action: Action = "mask"


class StagesConfig(BaseModel):
    rules: bool = True
    ner: bool = True
    llm_judge: Literal["always", "on_uncertain", "off"] = "on_uncertain"


class LLMJudgeConfig(BaseModel):
    model: str = "qwen2.5:7b-instruct"
    timeout_seconds: float = 8.0
    max_retries: int = 1


class MaskingConfig(BaseModel):
    restore_in_response: bool = False


class Policy(BaseModel):
    mode: Literal["mask", "block", "review"] = "mask"
    stages: StagesConfig = Field(default_factory=StagesConfig)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    kinds: dict[str, KindPolicy] = Field(default_factory=dict)
    on_judge_error: Action = "review"
    on_judge_only_detection: Action = "review"
    uncertain_without_judge: Action = "mask"
    llm_judge: LLMJudgeConfig = Field(default_factory=LLMJudgeConfig)
    masking: MaskingConfig = Field(default_factory=MaskingConfig)

    @field_validator("thresholds")
    @classmethod
    def _check_order(cls, t: Thresholds) -> Thresholds:
        if not (0 <= t.uncertain_low <= t.uncertain_high <= t.block_at <= 1):
            raise ValueError("thresholds は uncertain_low <= uncertain_high <= block_at の順")
        return t


def load_policy(path: str | Path) -> Policy:
    with open(path, encoding="utf-8") as f:
        return Policy.model_validate(yaml.safe_load(f) or {})


# ---- 環境変数 -----------------------------------------------------------------


@dataclass
class Settings:
    policy_path: Path = field(default_factory=lambda: Path("config/policy.yaml"))
    rules_path: Path = field(default_factory=lambda: Path("config/rules.yaml"))
    data_dir: Path = field(default_factory=lambda: Path("data"))
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ.get
        return cls(
            policy_path=Path(env("GUARD_POLICY_PATH", "config/policy.yaml")),
            rules_path=Path(env("GUARD_RULES_PATH", "config/rules.yaml")),
            data_dir=Path(env("GUARD_DATA_DIR", "data")),
            openai_base_url=env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_api_key=env("OPENAI_API_KEY", ""),
            openai_model=env("OPENAI_MODEL") or None,
            ollama_base_url=env("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            ollama_model=env("OLLAMA_MODEL") or None,
        )
