"""検査パイプライン。各段階を順に走らせ、Policy Engine に判定を委ねる。

早期終了: ある段階までの確定検出だけで block が決まるなら、
以降の段階（特に遅い Stage 3）は走らせない。
Stage 3 は Policy Engine が「必要」と言ったときだけ呼ぶ（既定は不確実帯の検出があるときだけ）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from llm_guard import policy as policy_engine
from llm_guard.config import Policy
from llm_guard.detectors.base import Detector, Finding
from llm_guard.masking import MaskMap, mask_text
from llm_guard.policy import JudgeVerdict

Judge = Callable[[str], JudgeVerdict]


class InspectionResult(BaseModel):
    decision: str
    findings: list[Finding]
    stages_run: list[str]
    timings_ms: dict[str, float]
    total_ms: float
    reason: str = ""
    masked_text: str | None = None
    judge: dict | None = None
    acted_findings: list[Finding] = []  # 判定に効いた検出（確定＋昇格）。評価の種類別集計に使う

    def public_findings(self) -> list[dict]:
        """原文（text）を含まない形。監査ログ用。"""
        return [
            {
                "kind": f.kind.value,
                "start": f.start,
                "end": f.end,
                "confidence": f.confidence,
                "stage": f.stage,
                "rule": f.rule,
            }
            for f in self.findings
        ]


@dataclass
class Guard:
    policy: Policy
    detectors: list[Detector] = field(default_factory=list)
    judge: Judge | None = None  # Stage 3。None なら無効
    judge_name: str = "llm_judge"

    def judge_enabled(self) -> bool:
        return self.judge is not None and self.policy.stages.llm_judge != "off"

    def inspect(self, text: str, mask_map: MaskMap | None = None) -> InspectionResult:
        t0 = time.perf_counter()
        findings: list[Finding] = []
        stages_run: list[str] = []
        timings: dict[str, float] = {}

        for det in self.detectors:
            if not det.ready():
                continue
            ts = time.perf_counter()
            findings.extend(det.detect(text))
            timings[det.name] = round((time.perf_counter() - ts) * 1000, 3)
            stages_run.append(det.name)
            if policy_engine.provisional(self.policy, findings) == "block":
                break  # 早期終了。これ以上調べても結果は変わらない

        verdict: JudgeVerdict | None = None
        decision = policy_engine.decide(self.policy, findings, None)
        if decision.judge_needed and decision.action != "block" and self.judge_enabled():
            assert self.judge is not None
            ts = time.perf_counter()
            verdict = self.judge(text)
            timings[self.judge_name] = round((time.perf_counter() - ts) * 1000, 3)
            stages_run.append(self.judge_name)
            decision = policy_engine.decide(self.policy, findings, verdict)
        elif decision.judge_needed:
            # Stage 3 が無効、または block 確定で不要。off 扱いで判定し直す
            decision = policy_engine.decide(
                self.policy.model_copy(
                    update={"stages": self.policy.stages.model_copy(update={"llm_judge": "off"})}
                ),
                findings,
                None,
            )

        masked = None
        if decision.action == "mask" and decision.to_mask:
            masked = mask_text(text, decision.to_mask, mask_map)

        return InspectionResult(
            decision=decision.action,
            findings=findings,
            stages_run=stages_run,
            timings_ms=timings,
            total_ms=round((time.perf_counter() - t0) * 1000, 3),
            reason=decision.reason,
            masked_text=masked,
            acted_findings=decision.to_mask,
            judge=(
                None
                if verdict is None
                else {
                    "sensitive": verdict.sensitive,
                    "kinds": verdict.kinds,
                    "reason": verdict.reason,
                    "error": verdict.error,
                }
            ),
        )
