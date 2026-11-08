"""設定から Guard（検査パイプライン）を組み立てる。アプリ本体と評価ハーネスの両方から使う。"""

from __future__ import annotations

from llm_guard.config import Policy, Settings, load_rules
from llm_guard.detectors.base import Detector
from llm_guard.detectors.rules import RulesDetector
from llm_guard.pipeline import Guard


def build_guard(policy: Policy, settings: Settings) -> Guard:
    detectors: list[Detector] = []
    if policy.stages.rules:
        detectors.append(RulesDetector(load_rules(settings.rules_path)))
    return Guard(policy=policy, detectors=detectors)
