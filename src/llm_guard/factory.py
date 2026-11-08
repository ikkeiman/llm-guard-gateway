"""設定から Guard（検査パイプライン）を組み立てる。アプリ本体と評価ハーネスの両方から使う。"""

from __future__ import annotations

from llm_guard.config import Policy, Settings, load_rules
from llm_guard.detectors.base import Detector
from llm_guard.detectors.llm_judge import OllamaJudge
from llm_guard.detectors.ner import NERDetector
from llm_guard.detectors.rules import RulesDetector
from llm_guard.pipeline import Guard


def build_guard(policy: Policy, settings: Settings, *, preload_ner: bool = False) -> Guard:
    detectors: list[Detector] = []
    if policy.stages.rules:
        detectors.append(RulesDetector(load_rules(settings.rules_path)))
    if policy.stages.ner:
        detectors.append(NERDetector(preload=preload_ner))
    judge = None
    if policy.stages.llm_judge != "off":
        judge = OllamaJudge(
            settings.ollama_base_url,
            settings.ollama_model or policy.llm_judge.model,
            timeout_seconds=policy.llm_judge.timeout_seconds,
            max_retries=policy.llm_judge.max_retries,
        )
    return Guard(policy=policy, detectors=detectors, judge=judge)
